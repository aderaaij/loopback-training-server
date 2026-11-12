"""The coach MCP, served from this process at /mcp.

One container, one port, one URL: an install that can reach the dashboard can
reach the coach. The MCP still talks to this API over HTTP (loopback) with the
caller's own token, exactly as it does when run on its own, so every tool call
goes through the same auth, user scoping and consent filtering as any other
client — nothing here gets a side door into the database.

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

from training_mcp.main import mcp

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

MCP_PATH = "/mcp"

# On by default; MCP_ENABLED=false serves no coach endpoint at all.
MCP_ENABLED = os.environ.get("MCP_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

# Streamable HTTP at the sub-app's root; its lifespan (the session manager)
# is entered from the API's own lifespan in main.py.
mcp_app = mcp.http_app(path="/") if MCP_ENABLED else None

_UNAUTHORIZED = json.dumps(
    {
        "detail": "The coach endpoint needs your own Loopback token: send "
        "'Authorization: Bearer <token>' (dashboard: Settings -> Create token)."
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

        # Presence only. The token is verified by the API on every call the
        # MCP makes with it; this just turns "no credentials" into a 401 at
        # the door instead of a tool error three steps into a session.
        headers = dict(scope.get("headers") or [])
        if not headers.get(b"authorization", b"").strip().lower().startswith(b"bearer "):
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                        (b"content-length", str(len(_UNAUTHORIZED)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _UNAUTHORIZED})
            return

        # What a mount does: the prefix moves to root_path, so the sub-app
        # sees its own "/" whether the client sent /mcp or /mcp/.
        child = dict(scope)
        child["root_path"] = scope.get("root_path", "") + MCP_PATH
        child["path"] = MCP_PATH + "/"
        child["raw_path"] = (MCP_PATH + "/").encode()
        await mcp_app(child, receive, send)
