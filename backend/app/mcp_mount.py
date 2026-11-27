"""The coach MCP, served from this process at /mcp.

One container, one port, one URL: an install that can reach the dashboard can
reach the coach. The MCP still talks to this API over HTTP (loopback) with the
caller's own token, exactly as it does when run on its own, so every tool call
goes through the same auth, user scoping and consent filtering as any other
client — nothing here gets a side door into the database. The one thing this
module reads there is whether the caller's token is still good, to answer 401
at the door (see MCPDispatch).

Why an ASGI wrapper rather than `app.mount("/mcp", ...)`: a Starlette mount
only matches `/mcp/...`, so a POST to the bare `/mcp` (what every MCP client
sends) falls through to the SPA catch-all, a GET-only route, and comes back
405 — indistinguishable from "this server has no MCP". Dispatching ahead of
the router sidesteps route order entirely.
"""

import json
import os
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.concurrency import run_in_threadpool
from training_mcp.main import mcp

from app.auth import token_is_live
from app.oauth import MCP_PATH, bearer_challenge, public_origin

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# On by default; MCP_ENABLED=false serves no coach endpoint at all.
MCP_ENABLED = os.environ.get("MCP_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

# Streamable HTTP at the sub-app's root; its lifespan (the session manager)
# is entered from the API's own lifespan in main.py.
mcp_app = mcp.http_app(path="/") if MCP_ENABLED else None

_NO_TOKEN = json.dumps(
    {
        "detail": "The coach endpoint needs your own Loopback token: send "
        "'Authorization: Bearer <token>' (dashboard: Settings -> Create token), "
        "or connect through an assistant that signs in for you."
    }
).encode()
_BAD_TOKEN = json.dumps(
    {
        "detail": "That token is not valid: it was revoked, has expired or was mistyped. "
        "Create a new one in the dashboard (Settings -> Create token), or reconnect the assistant."
    }
).encode()


class MCPDispatch:
    """Route /mcp to the MCP app; everything else to the API untouched."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if mcp_app is None or scope["type"] != "http" or path.rstrip("/") != MCP_PATH:
            await self.app(scope, receive, send)
            return

        # The door checks the token itself, although the API checks it again
        # on every call the MCP makes with it. A client that signed in through
        # OAuth only learns that it has to sign in again from a 401 here: if a
        # revoked token got a session, all it would see is tools failing. It
        # also means a stranger cannot open sessions with a made-up token.
        #
        # The challenge names the OAuth metadata, which is how such a client
        # finds out where to sign in (app/oauth.py).
        headers = dict(scope.get("headers") or [])
        authorization = headers.get(b"authorization", b"").strip()
        token = authorization[7:].strip().decode("latin-1") if authorization.lower().startswith(b"bearer ") else ""
        if not token or not await run_in_threadpool(token_is_live, token):
            body = _BAD_TOKEN if token else _NO_TOKEN
            challenge = bearer_challenge(public_origin(scope), invalid_token=bool(token))
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", challenge.encode("latin-1")),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        # What a mount does: the prefix moves to root_path, so the sub-app
        # sees its own "/" whether the client sent /mcp or /mcp/.
        child = dict(scope)
        child["root_path"] = scope.get("root_path", "") + MCP_PATH
        child["path"] = MCP_PATH + "/"
        child["raw_path"] = (MCP_PATH + "/").encode()
        await mcp_app(child, receive, send)
