"""OAuth for the coach endpoint: connecting an assistant by signing in.

The client's metadata document is the one thing fetched from outside, so the
fetcher is replaced by one that knows three documents: Claude's two as they
were published on 2026-11-27, and one from a host nobody has heard of.
"""

import asyncio
import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from fastmcp.server.auth.cimd import CIMDDocument, CIMDFetcher, CIMDFetchError
from sqlalchemy import select, update

import app.oauth as oauth
import app.routes.oauth as oauth_routes
from app.config import get_settings
from app.main import app
from app.models.api_token import ApiToken
from app.models.auth_event import AuthEvent
from app.models.oauth import OAuthAuthorization
from app.models.user import User

CLAUDE = "https://claude.ai/oauth/mcp-oauth-client-metadata"
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
CLAUDE_CODE = "https://claude.ai/oauth/claude-code-client-metadata"
STRANGER = "https://assistant.example/client.json"
SIGNING = "https://signing.example/client.json"
CHATGPT = "https://chatgpt.com/oauth/liW_65JNbHVJ/client.json"
CHATGPT_CALLBACK = "https://chatgpt.com/connector/oauth/liW_65JNbHVJ"

DOCUMENTS = {
    CLAUDE: {
        "client_id": CLAUDE,
        "client_name": "Claude",
        "client_uri": "https://claude.ai",
        "redirect_uris": [CLAUDE_CALLBACK],
        "grant_types": ["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:jwt-bearer"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    },
    CLAUDE_CODE: {
        "client_id": CLAUDE_CODE,
        "client_name": "Claude Code",
        "redirect_uris": ["http://localhost/callback", "http://127.0.0.1/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
    },
    STRANGER: {
        "client_id": STRANGER,
        "client_name": "Claude",  # anyone can call themselves that
        "redirect_uris": ["https://assistant.example/callback"],
        "token_endpoint_auth_method": "none",
    },
    SIGNING: {
        "client_id": SIGNING,
        "redirect_uris": ["https://signing.example/callback"],
        "token_endpoint_auth_method": "private_key_jwt",
        "jwks": {"keys": []},
    },
    # As ChatGPT published it on 2026-11-27 (one document per connector).
    CHATGPT: {
        "client_id": CHATGPT,
        "client_uri": "https://chatgpt.com/",
        "redirect_uris": [CHATGPT_CALLBACK],
        "token_endpoint_auth_method": "private_key_jwt",
        "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "client_name": "ChatGPT",
        "logo_uri": "https://persistent.oaistatic.com/sonic/misc/openai-logo.png",
        "token_endpoint_auth_signing_alg": "RS256",
        "jwks_uri": "https://chatgpt.com/oauth/jwks.json",
    },
}

VERIFIER = "a-verifier-long-enough-to-be-one-0123456789abcdef"
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()


@pytest.fixture(autouse=True)
def documents(monkeypatch):
    fetched = []

    async def fetch(client_id_url: str) -> CIMDDocument:
        fetched.append(client_id_url)
        if client_id_url not in DOCUMENTS:
            raise CIMDFetchError("no such document")
        return CIMDDocument.model_validate(DOCUMENTS[client_id_url])

    monkeypatch.setattr(oauth._fetcher, "fetch", fetch)
    return fetched


@pytest.fixture()
def anon():
    return TestClient(app, follow_redirects=False)


def authorize_params(**changes):
    params = {
        "response_type": "code",
        "client_id": CLAUDE,
        "redirect_uri": CLAUDE_CALLBACK,
        "state": "state-123",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "resource": "http://testserver/mcp",
    }
    params.update(changes)
    return {k: v for k, v in params.items() if v is not None}


def start(anon, **changes) -> str:
    """Send the browser to /oauth/authorize; returns the id of the waiting request."""
    r = anon.get("/oauth/authorize", params=authorize_params(**changes))
    assert r.status_code == 302, r.text
    target = urlsplit(r.headers["location"])
    assert target.path == "/oauth/consent" and not target.netloc
    return parse_qs(target.query)["request"][0]


def approve(client, request_id) -> dict[str, str]:
    """Approve as the client's user; returns the query the assistant gets back."""
    r = client.post(f"/api/oauth/requests/{request_id}/approve")
    assert r.status_code == 200, r.text
    target = urlsplit(r.json()["redirectTo"])
    return {"_base": f"{target.scheme}://{target.netloc}{target.path}", **{k: v[0] for k, v in parse_qs(target.query).items()}}


def trade(anon, code, **changes):
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CLAUDE,
        "redirect_uri": CLAUDE_CALLBACK,
        "code_verifier": VERIFIER,
        "resource": "http://testserver/mcp",
    }
    form.update(changes)
    return anon.post("/oauth/token", data={k: v for k, v in form.items() if v is not None})


# ── discovery ──


@pytest.mark.parametrize("path", ["/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"])
def test_the_resource_document_names_this_server(anon, path):
    r = anon.get(path)
    assert r.status_code == 200
    assert r.json() == {
        "resource": "http://testserver/mcp",
        "authorization_servers": ["http://testserver"],
        "bearer_methods_supported": ["header"],
        "resource_name": "Loopback coach",
    }


def test_the_server_document_is_what_claude_needs_to_skip_registration(anon):
    doc = anon.get("/.well-known/oauth-authorization-server").json()
    assert doc["issuer"] == "http://testserver"
    assert doc["authorization_endpoint"] == "http://testserver/oauth/authorize"
    assert doc["token_endpoint"] == "http://testserver/oauth/token"
    assert doc["code_challenge_methods_supported"] == ["S256"]
    # Claude picks its metadata document over registering only when it sees both.
    assert doc["client_id_metadata_document_supported"] is True
    assert doc["token_endpoint_auth_methods_supported"] == ["none"]
    assert "registration_endpoint" not in doc
    assert doc["grant_types_supported"] == ["authorization_code"]


# Behind Tailscale Serve or Caddy the server is spoken to over plain http on a
# loopback address; the documents have to carry the address the client used.
def test_the_documents_use_the_address_the_request_came_in_on(anon):
    headers = {"Host": "loopback.example:8443", "X-Forwarded-Proto": "https"}
    assert anon.get("/.well-known/oauth-protected-resource", headers=headers).json()["resource"] == (
        "https://loopback.example:8443/mcp"
    )
    headers = {"X-Forwarded-Host": "coach.example", "X-Forwarded-Proto": "https"}
    assert anon.get("/.well-known/oauth-authorization-server", headers=headers).json()["issuer"] == "https://coach.example"


def test_a_host_header_that_is_not_a_host_is_not_repeated(anon):
    r = anon.get("/.well-known/oauth-protected-resource", headers={"X-Forwarded-Host": 'evil"/><x'})
    assert "evil" not in r.text


def test_public_url_overrides_the_request(anon, monkeypatch):
    monkeypatch.setattr(get_settings(), "public_url", "https://set.example")
    headers = {"Host": "other.example", "X-Forwarded-Proto": "http"}
    assert anon.get("/.well-known/oauth-authorization-server", headers=headers).json()["issuer"] == "https://set.example"


# The approval page is only ever loaded by the athlete's browser, so it can
# sit on an address the assistant's servers cannot reach.
def test_the_approval_page_can_live_at_another_address(anon, monkeypatch):
    monkeypatch.setattr(get_settings(), "oauth_authorization_origin", "https://private.example:8443")
    doc = anon.get("/.well-known/oauth-authorization-server").json()
    assert doc["authorization_endpoint"] == "https://private.example:8443/oauth/authorize"
    assert doc["token_endpoint"] == "http://testserver/oauth/token"


# What deploy/tailscale sets: one name, the coach on the standard port and
# the dashboard on another. No name has to be written down for it.
def test_the_approval_page_can_be_the_same_name_on_another_port(anon, monkeypatch):
    monkeypatch.setattr(get_settings(), "oauth_authorization_port", 8443)
    public = {"Host": "loopback.tailnet.example", "X-Forwarded-Proto": "https"}
    doc = anon.get("/.well-known/oauth-authorization-server", headers=public).json()
    assert doc["issuer"] == "https://loopback.tailnet.example"
    assert doc["authorization_endpoint"] == "https://loopback.tailnet.example:8443/oauth/authorize"
    assert doc["token_endpoint"] == "https://loopback.tailnet.example/oauth/token"

    # Asked on the dashboard's own port, the server describes that entrance.
    private = {"Host": "loopback.tailnet.example:8443", "X-Forwarded-Proto": "https"}
    doc = anon.get("/.well-known/oauth-authorization-server", headers=private).json()
    assert doc["issuer"] == "https://loopback.tailnet.example:8443"
    assert doc["authorization_endpoint"] == "https://loopback.tailnet.example:8443/oauth/authorize"

    # A name written down wins over a port.
    monkeypatch.setattr(get_settings(), "oauth_authorization_origin", "https://elsewhere.example")
    doc = anon.get("/.well-known/oauth-authorization-server", headers=public).json()
    assert doc["authorization_endpoint"] == "https://elsewhere.example/oauth/authorize"


@pytest.mark.parametrize(
    "origin, port, expected",
    [
        ("https://host.example", 8443, "https://host.example:8443"),
        ("https://host.example:8443", None, "https://host.example"),
        ("https://host.example:8443", 443, "https://host.example"),
        ("http://host.example:8001", 80, "http://host.example"),
        ("https://[fd7a::1]:8443", 9000, "https://[fd7a::1]:9000"),
    ],
)
def test_the_same_host_on_another_port(origin, port, expected):
    assert oauth.on_port(origin, port) == expected


def test_documents_are_not_cached(anon):
    assert anon.get("/.well-known/oauth-authorization-server").headers["cache-control"] == "no-store"


def test_no_coach_endpoint_means_no_oauth(anon, monkeypatch):
    monkeypatch.setattr(oauth_routes, "MCP_ENABLED", False)
    assert anon.get("/.well-known/oauth-protected-resource").status_code == 404
    assert anon.get("/.well-known/oauth-authorization-server").status_code == 404
    assert anon.get("/oauth/authorize", params=authorize_params()).status_code == 404
    assert anon.post("/oauth/token", data={}).status_code == 404


# ── the whole way through ──


def test_connecting_ends_in_an_ordinary_token(anon, client_a, user_a, session_factory):
    request_id = start(anon)

    shown = client_a.get(f"/api/oauth/requests/{request_id}").json()
    assert shown["clientName"] == "Claude"
    assert shown["clientHost"] == "claude.ai"
    assert shown["recognised"] is True
    assert shown["redirectHost"] == "claude.ai"
    assert shown["loopback"] is False

    back = approve(client_a, request_id)
    assert back["_base"] == CLAUDE_CALLBACK
    assert back["state"] == "state-123"

    r = trade(anon, back["code"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer"
    assert body["access_token"].startswith("tapi_")
    assert "refresh_token" not in body and "expires_in" not in body
    assert r.headers["cache-control"] == "no-store"

    me = TestClient(app).get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"
    assert "Coach · Claude" in [t["name"] for t in me.json()["tokens"]]

    with session_factory() as db:
        assert db.scalars(select(OAuthAuthorization)).all() == []
        event = db.scalar(select(AuthEvent).where(AuthEvent.event == "token_created"))
        assert event.user_id == user_a[0]
        assert event.detail == {"name": "Coach · Claude", "via": "oauth"}


def test_a_code_works_once(anon, client_a):
    code = approve(client_a, start(anon))["code"]
    assert trade(anon, code).status_code == 200
    again = trade(anon, code)
    assert again.status_code == 400
    assert again.json()["error"] == "invalid_grant"


def test_the_code_is_stored_hashed(anon, client_a, session_factory):
    code = approve(client_a, start(anon))["code"]
    with session_factory() as db:
        row = db.scalar(select(OAuthAuthorization))
        assert row.code_hash == hashlib.sha256(code.encode()).hexdigest()
        assert code not in (row.state or "") + row.redirect_uri


@pytest.mark.parametrize(
    "changes, error",
    [
        ({"code_verifier": "not-the-verifier-that-made-the-challenge-0000000"}, "invalid_grant"),
        ({"redirect_uri": "https://claude.ai/somewhere/else"}, "invalid_request"),
        ({"code": "made-up"}, "invalid_grant"),
        ({"client_id": CLAUDE_CODE}, "invalid_grant"),
    ],
)
def test_a_code_is_only_good_for_the_request_it_came_from(anon, client_a, changes, error):
    code = approve(client_a, start(anon))["code"]
    r = trade(anon, **{"code": code, **changes})
    assert r.status_code == 400, r.text
    assert r.json()["error"] == error
    assert "access_token" not in r.json()


def test_a_code_expires(anon, client_a, session_factory):
    code = approve(client_a, start(anon))["code"]
    with session_factory() as db:
        row = db.scalar(select(OAuthAuthorization))
        # Approving shortens the time left to the code's own.
        assert row.expires_at - datetime.now(timezone.utc) <= oauth.CODE_TTL
        db.execute(update(OAuthAuthorization).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()
    r = trade(anon, code)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


def test_no_token_for_an_account_deactivated_in_between(anon, client_a, user_a, session_factory):
    code = approve(client_a, start(anon))["code"]
    with session_factory() as db:
        db.execute(update(User).where(User.id == user_a[0]).values(is_active=False))
        db.commit()
    r = trade(anon, code)
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"
    with session_factory() as db:
        assert db.scalars(select(ApiToken).where(ApiToken.name.like("Coach%"))).all() == []


def test_there_are_no_refresh_tokens(anon):
    r = anon.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": "x", "client_id": CLAUDE})
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


# ── approving ──


def test_approving_takes_a_signed_in_athlete(anon, session_factory):
    request_id = start(anon)
    for call in (
        lambda: anon.get(f"/api/oauth/requests/{request_id}"),
        lambda: anon.post(f"/api/oauth/requests/{request_id}/approve"),
        lambda: anon.post(f"/api/oauth/requests/{request_id}/deny"),
    ):
        assert call().status_code in (401, 403)
    with session_factory() as db:
        assert db.scalar(select(OAuthAuthorization)).code_hash is None


def test_an_admin_cannot_approve(anon, client_admin, client_a):
    request_id = start(anon)
    r = client_admin.post(f"/api/oauth/requests/{request_id}/approve")
    assert r.status_code == 403
    assert "no training data" in r.json()["detail"]
    # The request is still there for the athlete it was meant for.
    assert client_a.post(f"/api/oauth/requests/{request_id}/approve").status_code == 200


def test_a_request_is_answered_once(anon, client_a, client_b):
    request_id = start(anon)
    approve(client_a, request_id)
    assert client_a.post(f"/api/oauth/requests/{request_id}/approve").status_code == 404
    assert client_b.post(f"/api/oauth/requests/{request_id}/approve").status_code == 404
    assert client_a.get(f"/api/oauth/requests/{request_id}").status_code == 404
    assert client_a.post(f"/api/oauth/requests/{request_id}/deny").status_code == 404


def test_the_token_belongs_to_whoever_approved(anon, client_b):
    code = approve(client_b, start(anon))["code"]
    token = trade(anon, code).json()["access_token"]
    me = TestClient(app).get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["user"]["username"] == "bob"


def test_declining_tells_the_assistant_and_leaves_nothing_behind(anon, client_a, session_factory):
    request_id = start(anon)
    r = client_a.post(f"/api/oauth/requests/{request_id}/deny")
    assert r.status_code == 200
    target = urlsplit(r.json()["redirectTo"])
    query = {k: v[0] for k, v in parse_qs(target.query).items()}
    assert f"{target.scheme}://{target.netloc}{target.path}" == CLAUDE_CALLBACK
    assert query["error"] == "access_denied"
    assert query["state"] == "state-123"
    assert "code" not in query
    with session_factory() as db:
        assert db.scalars(select(OAuthAuthorization)).all() == []
    assert client_a.post(f"/api/oauth/requests/{request_id}/approve").status_code == 404


def test_a_request_nobody_answered_expires_and_is_cleared_out(anon, client_a, session_factory):
    request_id = start(anon)
    with session_factory() as db:
        db.execute(update(OAuthAuthorization).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()
    assert client_a.get(f"/api/oauth/requests/{request_id}").status_code == 404
    assert client_a.post(f"/api/oauth/requests/{request_id}/approve").status_code == 404

    newer = start(anon)
    with session_factory() as db:
        assert [str(r.id) for r in db.scalars(select(OAuthAuthorization))] == [newer]


def test_an_unknown_request_is_404(client_a):
    assert client_a.get(f"/api/oauth/requests/{uuid.uuid4()}").status_code == 404
    assert client_a.post(f"/api/oauth/requests/{uuid.uuid4()}/approve").status_code == 404


# ── who may ask ──


def test_a_client_nobody_can_vouch_for_is_turned_away(anon, session_factory):
    r = anon.get("/oauth/authorize", params=authorize_params(client_id="https://nowhere.example/client.json"))
    assert r.status_code == 400
    assert "location" not in r.headers
    with session_factory() as db:
        assert db.scalars(select(OAuthAuthorization)).all() == []


@pytest.mark.parametrize("client_id", ["some-name", "http://claude.ai/oauth/mcp-oauth-client-metadata", "https://claude.ai"])
def test_a_client_id_that_is_not_a_document_address_is_never_fetched(anon, documents, client_id):
    r = anon.get("/oauth/authorize", params=authorize_params(client_id=client_id))
    assert r.status_code == 400
    assert documents == []


# ChatGPT's document says it signs its token requests. This server offers one
# method, none, so it is taken as a public client like any other. The first
# version refused it, which kept ChatGPT out and protected nothing.
def test_chatgpt_can_sign_in(anon, client_a):
    request_id = start(anon, client_id=CHATGPT, redirect_uri=CHATGPT_CALLBACK, ui_locales="en-US")
    shown = client_a.get(f"/api/oauth/requests/{request_id}").json()
    assert shown["clientName"] == "ChatGPT"
    assert shown["clientHost"] == "chatgpt.com"
    assert shown["recognised"] is True

    back = approve(client_a, request_id)
    assert back["_base"] == CHATGPT_CALLBACK
    r = trade(anon, back["code"], client_id=CHATGPT, redirect_uri=CHATGPT_CALLBACK)
    assert r.status_code == 200, r.text
    me = TestClient(app).get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert "Coach · ChatGPT" in [t["name"] for t in me.json()["tokens"]]


# A signature such a client sends along is not looked at, and changes nothing
# about what is: the code still has to come with the verifier it was made for.
def test_a_client_that_signs_its_requests_is_held_to_the_same_checks(anon, client_a):
    signed = {
        "client_id": SIGNING,
        "redirect_uri": "https://signing.example/callback",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": "not.a.real-signature",
    }
    code = approve(client_a, start(anon, client_id=SIGNING, redirect_uri="https://signing.example/callback"))["code"]
    wrong = trade(anon, code, code_verifier="not-the-verifier-that-made-the-challenge-0000000", **signed)
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_grant"

    assert trade(anon, code, **signed).status_code == 200
    # Still shown by its host: only clients this server knows get their own name.
    request_id = start(anon, client_id=SIGNING, redirect_uri="https://signing.example/callback")
    assert client_a.get(f"/api/oauth/requests/{request_id}").json()["recognised"] is False


def test_the_code_only_goes_to_an_address_the_client_lists(anon):
    r = anon.get("/oauth/authorize", params=authorize_params(redirect_uri="https://evil.example/callback"))
    # Not a redirect: the address it would redirect to is the one in doubt.
    assert r.status_code == 400
    assert "location" not in r.headers


def test_a_request_without_pkce_gets_no_approval_page(anon, session_factory):
    r = anon.get("/oauth/authorize", params=authorize_params(code_challenge=None))
    assert r.status_code == 302
    assert r.headers["location"].startswith(CLAUDE_CALLBACK)
    assert "error=invalid_request" in r.headers["location"]
    with session_factory() as db:
        assert db.scalars(select(OAuthAuthorization)).all() == []


def test_a_scope_is_ignored_rather_than_refused(anon, client_a):
    code = approve(client_a, start(anon, scope="offline_access read"))["code"]
    assert trade(anon, code).status_code == 200


def test_a_stranger_calling_itself_claude_is_shown_by_its_host(anon, client_a):
    request_id = start(anon, client_id=STRANGER, redirect_uri="https://assistant.example/callback")
    shown = client_a.get(f"/api/oauth/requests/{request_id}").json()
    assert shown["clientHost"] == "assistant.example"
    assert shown["recognised"] is False

    code = approve(client_a, request_id)["code"]
    r = trade(anon, code, client_id=STRANGER, redirect_uri="https://assistant.example/callback")
    token = r.json()["access_token"]
    me = TestClient(app).get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    names = [t["name"] for t in me.json()["tokens"]]
    assert "Coach · assistant.example" in names
    assert "Coach · Claude" not in names


# An app on the athlete's own computer listens on whichever port is free.
def test_an_app_on_this_computer_may_use_any_port(anon, client_a):
    redirect = "http://localhost:53127/callback"
    request_id = start(anon, client_id=CLAUDE_CODE, redirect_uri=redirect)
    shown = client_a.get(f"/api/oauth/requests/{request_id}").json()
    assert shown["clientName"] == "Claude Code"
    assert shown["loopback"] is True

    back = approve(client_a, request_id)
    assert back["_base"] == redirect
    assert trade(anon, back["code"], client_id=CLAUDE_CODE, redirect_uri=redirect).status_code == 200


LISTED = ["https://claude.ai/api/mcp/auth_callback", "http://localhost/callback", "http://127.0.0.1/callback"]


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://claude.ai/api/mcp/auth_callback",
        "http://localhost/callback",
        "http://localhost:3118/callback",
        "http://127.0.0.1:53127/callback",
    ],
)
def test_redirects_that_are_allowed(redirect_uri):
    assert oauth.redirect_allowed(redirect_uri, LISTED)


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://claude.ai/api/mcp/auth_callback/extra",
        "https://claude.ai:8443/api/mcp/auth_callback",
        "https://claude.ai.evil.example/api/mcp/auth_callback",
        "https://claude.ai/api/mcp/auth_callback?next=https://evil.example",
        "https://claude.ai/api/mcp/auth_callback#fragment",
        # What a pattern match on the whole address would let through.
        "http://localhost:1@evil.example/callback",
        "http://localhost.evil.example/callback",
        "http://localhost:3118/other",
        "http://localhost:3118/callback?x=1",
        "https://localhost:3118/callback",
        "http://[::1]:3118/callback",
        "http://localhost:notaport/callback",
        "http://evil.example/callback",
        "",
    ],
)
def test_redirects_that_are_not(redirect_uri):
    assert not oauth.redirect_allowed(redirect_uri, LISTED)


# A client writes its own list, so being on it is not enough. The approval
# page sends the browser to this address: `javascript:` there would run the
# client's script inside the dashboard.
@pytest.mark.parametrize(
    "redirect_uri",
    [
        "javascript://assistant.example/%0Aalert(document.domain)",
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "cursor://anysphere.cursor/callback",
        "http://assistant.example/callback",
        "https:///callback",
    ],
)
def test_a_listed_address_still_has_to_be_a_safe_one(redirect_uri):
    assert not oauth.redirect_allowed(redirect_uri, [redirect_uri])


def test_a_client_listing_a_script_as_its_address_gets_nowhere(anon, monkeypatch, session_factory):
    script = "javascript://assistant.example/%0Aalert(document.domain)"
    monkeypatch.setitem(DOCUMENTS, STRANGER, {**DOCUMENTS[STRANGER], "redirect_uris": [script]})
    for sent in (script, None):  # named in the request, or left for the server to fill in
        r = anon.get("/oauth/authorize", params=authorize_params(client_id=STRANGER, redirect_uri=sent))
        assert r.status_code == 400
        assert "location" not in r.headers
    with session_factory() as db:
        assert db.scalars(select(OAuthAuthorization)).all() == []


def test_the_document_cache_has_a_ceiling(monkeypatch):
    fetcher = oauth._MetadataFetcher()
    seen = []

    async def fetch(self, client_id_url):
        seen.append(len(self._cache))
        self._cache[client_id_url] = object()
        return CIMDDocument.model_validate(DOCUMENTS[CLAUDE])

    async def fetch_many():
        for n in range(fetcher.MAX_CACHED + 2):
            await fetcher.fetch(f"https://client.example/{n}")

    monkeypatch.setattr(CIMDFetcher, "fetch", fetch)
    asyncio.run(fetch_many())
    assert max(seen) <= fetcher.MAX_CACHED
    assert len(fetcher._cache) <= fetcher.MAX_CACHED
