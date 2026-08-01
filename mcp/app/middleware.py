"""Session middleware: advertise only the tools the athlete shares.

Keyed on the caller's own token, because this server is multi-user by token
passthrough — two concurrent sessions can belong to different athletes with
different choices.

Filtering the *advertised list* rather than refusing the call is the whole
point. A tool that is listed and then errors produces a coach that retries,
apologises, and tells the athlete to go enable sleep tracking — reintroducing
in conversation exactly the nagging the app's own surfaces were built to avoid.
A tool that was never listed is simply never reasoned about.

A stale client-side tool list can still call an omitted tool; the backend
answers 403 with a message that says *not shared*, never *not recorded*.

The server instructions are NOT filtered here — FastMCP fixes them when the
connection opens, before middleware runs — which is why domain-specific
guidance belongs on the tools instead (see app/instructions.py).
"""

import logging
from typing import Any, Sequence

from fastmcp.server.middleware import Middleware, MiddlewareContext

from app.consent import shared_domains, tool_is_shared

logger = logging.getLogger(__name__)


class ConsentMiddleware(Middleware):
    async def on_list_tools(self, context: MiddlewareContext, call_next: Any) -> Sequence[Any]:
        tools = await call_next(context)
        try:
            domains = await shared_domains()
        except Exception:
            logger.exception("Consent lookup failed while listing tools; advertising all")
            return tools
        visible = [t for t in tools if tool_is_shared(t.name, domains)]
        if len(visible) != len(tools):
            hidden = sorted({t.name for t in tools} - {t.name for t in visible})
            logger.info(f"Consent filter hid {len(hidden)} tool(s): {', '.join(hidden)}")
        return visible
