"""OAuth endpoints for the coach (see app/oauth.py for the flow and the why).

Two routers. `public` is what an assistant and the athlete's browser reach
without a token: the two discovery documents, /oauth/authorize and
/oauth/token. It is registered ahead of the dashboard's catch-all route, which
would otherwise answer the discovery paths. `api` is the dashboard's approval
page talking to the server as the signed-in athlete, mounted under /api/oauth.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.token import TokenHandler
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app import oauth
from app.auth import CurrentUser
from app.database import DbSession
from app.mcp_mount import MCP_ENABLED
from app.rate_limit import limiter


def _coach_enabled() -> None:
    # No coach endpoint, nothing to sign in to.
    if not MCP_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


public = APIRouter(dependencies=[Depends(_coach_enabled)], include_in_schema=False)
api = APIRouter(dependencies=[Depends(_coach_enabled)])

# A cache between the server and a client must not hand one caller's document
# to the next: the document is written for the address each request came in on.
_NO_STORE = {"Cache-Control": "no-store"}


# The second spelling is where RFC 9728 puts the document for a resource at
# /mcp; clients that were not told where to look try both.
@public.get(oauth.RESOURCE_METADATA_PATH)
@public.get(oauth.RESOURCE_METADATA_PATH + oauth.MCP_PATH)
def protected_resource(request: Request) -> JSONResponse:
    return JSONResponse(oauth.protected_resource_metadata(oauth.public_origin(request.scope)), headers=_NO_STORE)


@public.get(oauth.SERVER_METADATA_PATH)
def authorization_server(request: Request) -> JSONResponse:
    return JSONResponse(oauth.authorization_server_metadata(oauth.public_origin(request.scope)), headers=_NO_STORE)


# Both of these make the server fetch the client's metadata document, and
# authorize also writes a row, for anyone who asks.
@public.api_route(oauth.AUTHORIZE_PATH, methods=["GET", "POST"])
@limiter.limit("30/minute")
async def authorize(request: Request, db: DbSession) -> Response:
    return await AuthorizationHandler(oauth.CoachOAuthProvider(db, request)).handle(request)


@public.post(oauth.TOKEN_PATH)
@limiter.limit("30/minute")
async def token(request: Request, db: DbSession) -> Response:
    provider = oauth.CoachOAuthProvider(db, request)
    return await TokenHandler(provider, ClientAuthenticator(provider)).handle(request)


# ── the approval page ──


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ConsentRequest(_CamelModel):
    id: uuid.UUID
    client_name: str | None
    client_host: str
    recognised: bool
    redirect_host: str
    loopback: bool
    expires_at: datetime


class Redirect(_CamelModel):
    redirect_to: str


_GONE = "This request has expired or was already answered. Start again from your assistant."


@api.get("/requests/{request_id}", response_model=ConsentRequest)
def consent_request(request_id: uuid.UUID, db: DbSession) -> ConsentRequest:
    row = oauth.waiting_request(db, request_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_GONE)
    return ConsentRequest(**oauth.describe(row))


@api.post("/requests/{request_id}/approve", response_model=Redirect)
def approve(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Redirect:
    if user.role == "admin":
        # An admin has no training data; the token would be one to the
        # account-management API and nothing a coach can use.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An admin account has no training data to share. Sign in as the athlete instead.",
        )
    target = oauth.approve(db, request_id, user)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_GONE)
    return Redirect(redirect_to=target)


@api.post("/requests/{request_id}/deny", response_model=Redirect)
def deny(request_id: uuid.UUID, db: DbSession) -> Redirect:
    target = oauth.deny(db, request_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_GONE)
    return Redirect(redirect_to=target)
