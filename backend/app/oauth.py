"""OAuth for the coach endpoint.

With this an assistant is connected by giving it the server's address and
signing in, instead of creating a token and pasting it into a config file. It
is the only way in for assistants that run in the cloud (claude.ai on the web
and phone, the connector dialog in Claude Desktop), which cannot be handed a
header.

The flow, and who makes each request:

1. The assistant's servers POST to /mcp without a token and get a 401 that
   names /.well-known/oauth-protected-resource. They read that and
   /.well-known/oauth-authorization-server (routes/oauth.py).
2. The athlete's own browser is sent to /oauth/authorize, which checks the
   request and passes them on to the dashboard's approval page.
3. Approving there sends the browser back to the assistant with a one-time
   code, which the assistant's servers trade at /oauth/token for a token.

Things worth not re-deriving:

- **The token is an ordinary `api_tokens` row.** The MCP already forwards the
  caller's bearer token to the API, so nothing downstream knows or cares how a
  token was obtained, and it shows up under Settings like any other, where
  the athlete can revoke it. It does not expire and there is no refresh token:
  that is what every other coach token already is, and a refresh that fails
  disconnects the coach for a reason the athlete cannot see.
- **The request handling is the MCP SDK's, not ours.** `AuthorizationHandler`
  and `TokenHandler` validate the requests, compare the redirect address and
  check the PKCE proof. This module supplies what they ask a provider for:
  who the client is, where to send the athlete, and the storage.
- **Clients identify themselves with a metadata document** (the client id is
  the https address of a small JSON file the client publishes, "CIMD"), so
  there is no registration endpoint and no table of clients that strangers
  could fill. Fetching that address is the one place the server goes out to
  an address a stranger chose; FastMCP's fetcher refuses anything that is not
  public https and pins the address it resolved.
- **Step 2 can live at another address than steps 1 and 3**
  (`OAUTH_AUTHORIZATION_ORIGIN`), because only the athlete's browser ever
  loads it. That is what lets a server keep its dashboard, and with it every
  page that takes a password, on a private network while the coach endpoint
  is public. Checked against claude.ai on 2026-11-27.
- **The server describes itself by the address a request arrived at**, taken
  from the Host and X-Forwarded-* headers without asking whether the sender
  may set them. A caller who lies there gets documents describing the wrong
  server and nobody else does, and nothing is decided on that address.
"""

import logging
import re
import secrets
import uuid
from collections.abc import MutableMapping
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from fastmcp.server.auth.cimd import CIMDDocument, CIMDFetcher, CIMDFetchError, CIMDValidationError
from mcp.server.auth.provider import AuthorizationCode, AuthorizationParams, TokenError, construct_redirect_uri
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl, ValidationError
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from app.auth_events import client_ip, record_auth_event
from app.config import get_settings
from app.models.api_token import ApiToken
from app.models.oauth import OAuthAuthorization
from app.models.user import User
from app.security import generate_token, hash_token

logger = logging.getLogger("uvicorn.error")

MCP_PATH = "/mcp"
AUTHORIZE_PATH = "/oauth/authorize"
TOKEN_PATH = "/oauth/token"
CONSENT_PATH = "/oauth/consent"
RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
SERVER_METADATA_PATH = "/.well-known/oauth-authorization-server"

# How long the athlete has to sign in and approve, and how long the assistant
# then has to trade the code in (it does so within a second or two).
REQUEST_TTL = timedelta(minutes=10)
CODE_TTL = timedelta(minutes=2)

# Clients whose own name is shown on the approval page. Anyone can publish a
# metadata document that calls itself "Claude"; for every other host the page
# leads with the host, which cannot be made up.
RECOGNISED_CLIENT_HOSTS = frozenset({"claude.ai"})

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_HOST_RE = re.compile(r"^(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?$")


# ── the server's own address ──


def public_origin(scope: MutableMapping[str, Any]) -> str:
    """The server's address as the caller sees it, e.g. https://host:8443."""
    configured = get_settings().public_url
    if configured:
        return configured
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers") or []}
    scheme = headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if scheme not in ("http", "https"):
        scheme = scope.get("scheme", "http")
    host = (headers.get("x-forwarded-host") or headers.get("host") or "").split(",")[0].strip()
    if not _HOST_RE.fullmatch(host):
        server = scope.get("server") or ("localhost", 80)
        host = f"{server[0]}:{server[1]}"
    return f"{scheme}://{host}"


def protected_resource_metadata(origin: str) -> dict[str, Any]:
    return {
        "resource": origin + MCP_PATH,
        "authorization_servers": [origin],
        "bearer_methods_supported": ["header"],
        "resource_name": "Loopback coach",
    }


def authorization_server_metadata(origin: str) -> dict[str, Any]:
    authorize_origin = get_settings().oauth_authorization_origin or origin
    return {
        "issuer": origin,
        "authorization_endpoint": authorize_origin + AUTHORIZE_PATH,
        "token_endpoint": origin + TOKEN_PATH,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        # Both of these together are what makes Claude identify itself by its
        # metadata document instead of trying to register.
        "token_endpoint_auth_methods_supported": ["none"],
        "client_id_metadata_document_supported": True,
    }


def bearer_challenge(origin: str, *, invalid_token: bool = False) -> str:
    """The WWW-Authenticate value on a 401 from /mcp: where to start step 1."""
    value = f'Bearer resource_metadata="{origin}{RESOURCE_METADATA_PATH}{MCP_PATH}"'
    if invalid_token:
        value += ', error="invalid_token"'
    return value


# ── clients ──


def redirect_allowed(redirect_uri: str, registered: list[str]) -> bool:
    """Whether a client may be sent back to `redirect_uri`.

    The address has to be one the client's metadata document lists, exactly.
    The one exception is RFC 8252's: an app on the athlete's own computer
    listens on whichever port is free, so for http://localhost and
    http://127.0.0.1 the port is not compared. No wildcards beyond that: a
    pattern match on a whole address is how a code ends up at
    `http://localhost:1@evil.example/callback`.

    Whatever the document lists, the address must be https, or http to this
    computer. The approval page sends the browser there, and a document is
    free to list `javascript:` as an address: followed, that would run the
    client's script inside the dashboard, with the athlete's own token in
    reach. It also keeps a code from crossing a network in the clear. An app
    that wants the code on a scheme of its own (`cursor://`) is not supported.
    """
    try:
        asked = urlsplit(redirect_uri)
        asked.port  # noqa: B018 - raises on a port that is not a number
    except ValueError:
        return False
    if asked.fragment or "@" in asked.netloc or not asked.hostname:
        return False
    if asked.scheme != "https" and not (asked.scheme == "http" and asked.hostname in _LOOPBACK_HOSTS):
        return False
    for entry in registered:
        try:
            known = urlsplit(entry)
        except ValueError:
            continue
        if known.scheme == "http" and known.hostname in _LOOPBACK_HOSTS:
            if (asked.scheme, asked.hostname, asked.path, asked.query) == ("http", known.hostname, known.path, known.query):
                return True
        elif _normalised(entry) == _normalised(redirect_uri):
            return True
    return False


def _normalised(url: str) -> str:
    try:
        return str(AnyUrl(url))
    except ValidationError:
        return url


class CoachClient(OAuthClientInformationFull):
    """A client as its metadata document describes it."""

    # As the document lists them. Kept apart from `redirect_uris`, which the
    # SDK compares by equality only.
    registered_redirect_uris: list[str] = []

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            if len(self.registered_redirect_uris) != 1:
                raise InvalidRedirectUriError("redirect_uri must be specified when the client lists more than one")
            # The only one it lists goes through the same checks as one it sent.
            redirect_uri = AnyUrl(self.registered_redirect_uris[0])
        if not redirect_allowed(str(redirect_uri), self.registered_redirect_uris):
            raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' is not one this client lists")
        return redirect_uri

    def validate_scope(self, requested_scope: str | None) -> list[str] | None:
        # There are no scopes: a token is the athlete's own. A client that asks
        # for some is not refused, it just does not get them.
        return None


class _MetadataFetcher(CIMDFetcher):
    """FastMCP's fetcher, with a ceiling on what it keeps.

    It caches every document it has fetched, and anyone can make it fetch one
    more by naming a new address, so without a ceiling the cache is as large
    as a stranger cares to make it.
    """

    MAX_CACHED = 64

    async def fetch(self, client_id_url: str) -> CIMDDocument:
        if client_id_url not in self._cache and len(self._cache) >= self.MAX_CACHED:
            self._cache.clear()
        return await super().fetch(client_id_url)


_fetcher = _MetadataFetcher()


async def resolve_client(client_id: str) -> CoachClient | None:
    """The client behind a client id, or None when it cannot be vouched for."""
    if not _fetcher.is_cimd_client_id(client_id):
        return None
    try:
        document = await _fetcher.fetch(client_id)
    except (CIMDFetchError, CIMDValidationError) as exc:
        logger.warning("OAuth: could not read client metadata at %s: %s", client_id, exc)
        return None
    if document.token_endpoint_auth_method != "none":
        # A client that signs its token requests. Nothing here checks such a
        # signature, and accepting the client without checking it would be
        # worse than refusing it.
        logger.warning("OAuth: client %s uses %s, which is not supported", client_id, document.token_endpoint_auth_method)
        return None
    return CoachClient(
        client_id=client_id,
        client_name=_clean(document.client_name),
        redirect_uris=None,
        registered_redirect_uris=list(document.redirect_uris),
        grant_types=["authorization_code"],
        token_endpoint_auth_method="none",
    )


def _clean(name: str | None) -> str | None:
    """A client's own name, made safe to show and to store."""
    if not name:
        return None
    name = "".join(ch for ch in name if ch.isprintable()).strip()
    return name[:60] or None


def client_host(client_id: str) -> str:
    return urlsplit(client_id).hostname or client_id


def client_label(client_id: str, client_name: str | None) -> str:
    """What to call a client: its own name if its host is known, else the host."""
    host = client_host(client_id)
    if client_name and host in RECOGNISED_CLIENT_HOSTS:
        return client_name
    return host


def describe(row: OAuthAuthorization) -> dict[str, Any]:
    """What the approval page shows about a waiting request."""
    target = urlsplit(row.redirect_uri)
    host = client_host(row.client_id)
    return {
        "id": row.id,
        "client_name": row.client_name,
        "client_host": host,
        "recognised": host in RECOGNISED_CLIENT_HOSTS,
        "redirect_host": target.hostname or "",
        # The code goes to a program on the athlete's own computer.
        "loopback": target.scheme == "http" and target.hostname in _LOOPBACK_HOSTS,
        "expires_at": row.expires_at,
    }


# ── the approval page's side ──


def _now() -> datetime:
    return datetime.now(timezone.utc)


def waiting_request(db: Session, request_id: uuid.UUID) -> OAuthAuthorization | None:
    """A request that is still waiting for an answer."""
    return db.scalar(
        select(OAuthAuthorization).where(
            OAuthAuthorization.id == request_id,
            OAuthAuthorization.code_hash.is_(None),
            OAuthAuthorization.expires_at > _now(),
        )
    )


def approve(db: Session, request_id: uuid.UUID, user: User) -> str | None:
    """Approve a waiting request as `user`. Returns where to send the browser.

    One statement, so two clicks (or two tabs) cannot both turn the same
    request into a code.
    """
    code = secrets.token_urlsafe(32)
    now = _now()
    row = db.execute(
        update(OAuthAuthorization)
        .where(
            OAuthAuthorization.id == request_id,
            OAuthAuthorization.code_hash.is_(None),
            OAuthAuthorization.expires_at > now,
        )
        .values(user_id=user.id, code_hash=hash_token(code), expires_at=now + CODE_TTL)
        .returning(OAuthAuthorization.redirect_uri, OAuthAuthorization.state)
    ).first()
    db.commit()
    if row is None:
        return None
    return construct_redirect_uri(row.redirect_uri, code=code, state=row.state)


def deny(db: Session, request_id: uuid.UUID) -> str | None:
    """Turn a waiting request down. Returns where to send the browser."""
    row = db.execute(
        delete(OAuthAuthorization)
        .where(OAuthAuthorization.id == request_id, OAuthAuthorization.code_hash.is_(None))
        .returning(OAuthAuthorization.redirect_uri, OAuthAuthorization.state)
    ).first()
    db.commit()
    if row is None:
        return None
    return construct_redirect_uri(
        row.redirect_uri, error="access_denied", error_description="The request was declined", state=row.state
    )


# ── what the SDK's handlers ask for ──


class IssuedCode(AuthorizationCode):
    authorization_id: uuid.UUID


class CoachOAuthProvider:
    """Storage and decisions behind the SDK's authorize and token handlers.

    One per request, around that request's database session. The session is
    synchronous, so each piece of database work runs in the thread pool.
    """

    def __init__(self, db: Session, request: Request) -> None:
        self.db = db
        self.request = request

    async def get_client(self, client_id: str) -> CoachClient | None:
        return await resolve_client(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("Clients identify themselves with a metadata document")

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        request_id = await run_in_threadpool(self._open, client, params)
        # Relative, so the browser stays on the address it came in on.
        return f"{CONSENT_PATH}?request={request_id}"

    def _open(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> uuid.UUID:
        now = _now()
        # Nothing else clears out requests nobody answered.
        self.db.execute(delete(OAuthAuthorization).where(OAuthAuthorization.expires_at < now))
        row = OAuthAuthorization(
            client_id=client.client_id,
            client_name=client.client_name,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            state=params.state,
            code_challenge=params.code_challenge,
            resource=params.resource,
            expires_at=now + REQUEST_TTL,
        )
        self.db.add(row)
        self.db.commit()
        return row.id

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> IssuedCode | None:
        return await run_in_threadpool(self._load, authorization_code)

    def _load(self, code: str) -> IssuedCode | None:
        row = self.db.scalar(select(OAuthAuthorization).where(OAuthAuthorization.code_hash == hash_token(code)))
        if row is None or row.user_id is None:
            return None
        return IssuedCode(
            code=code,
            scopes=[],
            expires_at=row.expires_at.timestamp(),
            client_id=row.client_id,
            code_challenge=row.code_challenge,
            redirect_uri=AnyUrl(row.redirect_uri),
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            resource=row.resource,
            authorization_id=row.id,
        )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: IssuedCode) -> OAuthToken:
        token = await run_in_threadpool(self._trade, authorization_code)
        return OAuthToken(access_token=token, token_type="Bearer")

    def _trade(self, code: IssuedCode) -> str:
        # Deleting the row is what spends the code: of two requests carrying
        # the same one, only the first gets a row back.
        row = self.db.execute(
            delete(OAuthAuthorization)
            .where(
                OAuthAuthorization.id == code.authorization_id,
                OAuthAuthorization.code_hash == hash_token(code.code),
            )
            .returning(OAuthAuthorization.user_id, OAuthAuthorization.client_id, OAuthAuthorization.client_name)
        ).first()
        user = self.db.get(User, row.user_id) if row is not None else None
        if row is None or user is None or not user.is_active:
            self.db.commit()
            raise TokenError("invalid_grant", "authorization code does not exist")

        raw = generate_token()
        name = f"Coach · {client_label(row.client_id, row.client_name)}"
        self.db.add(ApiToken(user_id=user.id, token_hash=hash_token(raw), name=name))
        record_auth_event(
            self.db, "token_created", username=user.username, user_id=user.id, actor_user_id=user.id,
            ip=client_ip(self.request), detail={"name": name, "via": "oauth"},
        )
        self.db.commit()
        return raw

    # No refresh tokens are issued, and a client is never given the
    # refresh_token grant, so the handler turns such a request down before
    # asking for either of these.
    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> None:
        return None

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: Any, scopes: list[str]) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "This server does not issue refresh tokens")

    async def load_access_token(self, token: str) -> None:
        return None

    async def revoke_token(self, token: Any) -> None:
        return None
