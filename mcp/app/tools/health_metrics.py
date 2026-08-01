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

    One row per day. Which metrics a row carries varies by athlete — sleep,
    resting HR, HRV, respiratory rate, SpO2, weight, body composition, VO2Max,
    steps and energy are all possible. Read the fields that are present rather
    than assuming a fixed set; a field that isn't there is not a zero, and not
    something to ask the athlete to start recording.

    Where energy is present: `active_energy_burned` is movement + exercise (it
    already includes workout calories); `basal_energy_burned` is resting burn,
    and may be null on older app builds. Their sum is total daily expenditure.
    For anything comparing expenditure against intake, prefer
    get_nutrition_summary — it aligns both sides on the same periods and
    excludes days still in progress, which these raw rows do not.

    Use these to correlate recovery/readiness with training patterns:
    - Low HRV + poor sleep → suggest an easier workout or a rest day
    - Declining resting HR trend → improving cardiovascular fitness
    - Weight/body composition trends alongside training volume
    - Steps and active energy alongside training load: how much of the day's
      movement was the session, and how much was the rest of life

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
