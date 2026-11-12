"""Text-only tool results.

FastMCP ships every tool result twice: once as JSON text content and again as
``structuredContent`` (wrapped in ``{"result": ...}`` whenever the return
annotation isn't a plain object schema). Our only consumer is an LLM reading
the text channel, so doubling the wire payload buys nothing — and the wrapper
leaks confusingly when a list is empty (empty text content makes clients fall
back to displaying ``{"result": []}``).

``@text_result`` makes a tool return its value as compact JSON text content
only: no structured content, no wrapper, empty lists render as ``[]``.
"""

import functools
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent


def wire(result: Any) -> ToolResult:
    text = result if isinstance(result, str) else json.dumps(result, separators=(",", ":"), default=str)
    return ToolResult(content=[TextContent(type="text", text=text)])


def text_result(fn: Callable[..., Any]) -> Callable[..., Awaitable[ToolResult]]:
    """Wrap a tool function (sync or async) so its return value ships as
    text-only content. Apply UNDER the ``@router.tool`` decorator. The return
    annotation is rewritten to ToolResult so FastMCP generates no output schema
    (an output schema would both re-wrap the result and require
    structuredContent).
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> ToolResult:
        result = fn(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return wire(result)

    # functools.wraps points inspect.signature at fn (via __wrapped__), which
    # would resurrect fn's `dict | list` return annotation — override both
    # lookup paths FastMCP might use.
    wrapper.__signature__ = inspect.signature(fn).replace(return_annotation=ToolResult)
    wrapper.__annotations__ = {**fn.__annotations__, "return": ToolResult}
    return wrapper
