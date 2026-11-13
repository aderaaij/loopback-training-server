from fastapi import APIRouter
from sqlalchemy import text

from app.database import DbSession
from app.mcp_mount import MCP_ENABLED
from app.version import __version__

router = APIRouter()


@router.get("/health")
def health(db: DbSession):
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"

    return {
        "service": "training-api",
        "version": __version__,
        "database": db_status,
        # Lets the dashboard hide its "connect your coach" setup when the
        # endpoint is switched off. Not a secret: anyone can probe /mcp.
        "mcp": MCP_ENABLED,
    }
