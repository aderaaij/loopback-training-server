"""MCP tools for querying daily health metrics."""

import logging

from fastmcp import FastMCP

from app.services.api_client import client
from app.wire import text_result

logger = logging.getLogger(__name__)

health_metrics_router = FastMCP("health-metrics")


@health_metrics_router.tool()
@text_result
async def get_health_metrics(
    start_date: str,
    end_date: str | None = None,
) -> list | dict:
    """Get daily health metrics synced from HealthKit.

    Returns metrics like sleep, resting heart rate, HRV, weight, VO2Max,
    steps, active energy, basal energy, body fat, respiratory rate, and SpO2.

    `active_energy_burned` is movement + exercise (it already includes workout
    calories); `basal_energy_burned` is resting burn, and may be null on older
    app builds. Their sum is total daily expenditure. For anything comparing
    expenditure against intake, prefer get_nutrition_summary — it aligns both
    sides on the same periods and excludes days still in progress, which these
    raw rows do not.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD), defaults to today
    """
    try:
        return await client.get_health_metrics(
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as e:
        logger.error(f"Failed to get health metrics: {e}")
        return {"error": str(e)}
