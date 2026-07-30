"""MCP tools for querying dietary intake synced from HealthKit."""

import logging

from fastmcp import FastMCP

from app.services.api_client import client
from app.wire import text_result

logger = logging.getLogger(__name__)

nutrition_router = FastMCP("nutrition")


@nutrition_router.tool()
@text_result
async def get_nutrition(
    start_date: str,
    end_date: str | None = None,
    limit: int | None = 60,
) -> list | dict:
    """Get daily nutrition totals synced from HealthKit (food logging apps).

    Returns one row per day that has logged food: energy (kcal), carbs, protein,
    fat, saturated fat, fiber, sugar, sodium, potassium, cholesterol, water,
    caffeine, plus any extra micronutrients under `micros`, the number of
    logged entries and which apps wrote them.

    Days with no logging have NO row — absence means "not tracked", not "ate
    nothing". A row with `partial: true` was synced while the day was still in
    progress, so its totals are incomplete; exclude those from any average.

    For trends over more than a couple of weeks, prefer get_nutrition_summary —
    it aggregates per week or month and aligns intake with weight and training
    load, at a fraction of the tokens.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD), defaults to today
        limit: Max days returned, newest first (default 60)
    """
    try:
        return await client.get_nutrition(
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Failed to get nutrition: {e}")
        return {"error": str(e)}


@nutrition_router.tool()
@text_result
async def get_nutrition_summary(
    start_date: str,
    end_date: str | None = None,
    period: str = "week",
    timezone: str | None = None,
) -> list | dict:
    """Diet, body weight and training load aligned on the same periods.

    This is the tool for "is my nutrition supporting my training?". Each period
    carries:
      - `nutrition`: average intake per LOGGED day (partial days excluded)
      - `days_logged` / `days_in_period`: how much of the period that average
        actually covers — 2 of 7 days is an anecdote, not a weekly average
      - `protein_g_per_kg`: protein against the period's average body weight
      - `body`: weight start/end/avg and the change across the period
      - `training`: workouts, distance, duration and energy burned

    Read `days_logged` before drawing any conclusion, and remember intake is
    self-reported: food logging typically under-reports, so treat the *trend*
    and the macro split as the signal rather than absolute calorie totals.
    Weight change over a single week is mostly glycogen and hydration; look
    across 3-4 weeks before calling it a trend.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD), defaults to today
        period: "week" (default) or "month"
        timezone: IANA zone (e.g. "Europe/Amsterdam") used to attribute
            workouts to a local day; defaults to UTC
    """
    try:
        return await client.get_nutrition_summary(
            start_date=start_date,
            end_date=end_date,
            period=period,
            timezone=timezone,
        )
    except Exception as e:
        logger.error(f"Failed to get nutrition summary: {e}")
        return {"error": str(e)}
