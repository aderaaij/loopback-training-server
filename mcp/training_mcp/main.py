"""Training MCP Server - Main entry point."""

import logging
import os
from datetime import date

from fastmcp import FastMCP

from training_mcp import instructions
from training_mcp.config import ENV_FILE, settings
from training_mcp.middleware import ConsentMiddleware
from training_mcp.tools.actions import actions_router
from training_mcp.tools.coaching import coaching_router
from training_mcp.tools.feedback import feedback_router
from training_mcp.tools.health_metrics import health_metrics_router
from training_mcp.tools.nutrition import nutrition_router
from training_mcp.tools.plan_notes import plan_notes_router
from training_mcp.tools.plans import plans_router
from training_mcp.tools.queue import queue_router
from training_mcp.tools.workouts import workouts_router

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "training-mcp",
    # Training-wide only. Anything specific to a health domain lives on the
    # tool that serves it, because tools are filtered per athlete and these
    # are not — see training_mcp/instructions.py.
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


def main() -> None:
    """Entry point for the standalone MCP server.

    The published Docker image does not use this: the backend mounts `mcp`
    in-process at /mcp (backend/app/mcp_mount.py). This is for running the MCP
    on its own — stdio for a client that launches it, or a separate HTTP port.

    Default transport is stdio (direct clients, or wrapped by supergateway).
    Set MCP_TRANSPORT=http (with MCP_HOST / MCP_PORT) to serve streamable HTTP
    natively — no supergateway needed; point clients at http://<host>:<port>/mcp
    """
    # Process-wide setup lives here, not at import: imported by the backend,
    # this module must not reconfigure the host process's logging.
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    if not settings.is_configured() and not settings.require_auth_header:
        logger.warning(
            "TRAINING_API_KEY not set (expected in %s); only callers sending their own "
            "Authorization header will work.",
            ENV_FILE,
        )
    logger.info(f"Training MCP server starting. API URL: {settings.training_api_url}")

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
