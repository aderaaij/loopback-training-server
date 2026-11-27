"""Downloads that help an athlete connect an AI client to the coach at /mcp."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.coach_extension import FILENAME, build_bundle, clean_server_url
from app.mcp_mount import MCP_ENABLED
from app.version import __version__

router = APIRouter()


@router.get("/claude-desktop.mcpb")
def claude_desktop_extension(
    # The address the athlete has the dashboard open at, which is the one
    # their computer can reach. The server cannot know it: behind a proxy or
    # Tailscale Serve it sees its own loopback address.
    server_url: Annotated[str | None, Query(alias="serverUrl", max_length=2048)] = None,
) -> Response:
    if not MCP_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The coach endpoint is switched off")
    try:
        origin = clean_server_url(server_url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return Response(
        content=build_bundle(__version__, origin),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{FILENAME}"',
            "Cache-Control": "no-store",
        },
    )
