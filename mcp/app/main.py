"""Training MCP Server - Main entry point."""

import logging
import os
from datetime import date

from fastmcp import FastMCP

from app import instructions
from app.config import settings
from app.middleware import ConsentMiddleware
from app.tools.actions import actions_router
from app.tools.coaching import coaching_router
from app.tools.feedback import feedback_router
from app.tools.health_metrics import health_metrics_router
from app.tools.nutrition import nutrition_router
from app.tools.plan_notes import plan_notes_router
from app.tools.plans import plans_router
from app.tools.queue import queue_router
from app.tools.workouts import workouts_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "training-mcp",
    # Training-wide only. Anything specific to a health domain lives on the
    # tool that serves it, because tools are filtered per athlete and these
    # are not — see app/instructions.py.
    instructions=instructions.build(date.today().isoformat()),
)

mcp.add_middleware(ConsentMiddleware())

mcp.mount(coaching_router)
mcp.mount(workouts_router)
mcp.mount(queue_router)
mcp.mount(actions_router)
mcp.mount(feedback_router)
mcp.mount(health_metrics_router)
mcp.mount(nutrition_router)
mcp.mount(plans_router)
mcp.mount(plan_notes_router)

logger.info(f"Training MCP server initialized. API URL: {settings.training_api_url}")


def main() -> None:
    """Entry point for the MCP server.

    Default transport is stdio (direct clients, or wrapped by supergateway).
    Set MCP_TRANSPORT=http (with MCP_HOST / MCP_PORT) to serve streamable HTTP
    natively — no supergateway needed; point clients at http://<host>:<port>/mcp
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    if transport in ("http", "streamable-http"):
        mcp.run(
            transport="http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8590")),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    main()
