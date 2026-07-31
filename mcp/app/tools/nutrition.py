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

    ONLY `energy_kcal`, `carbs_g`, `protein_g` and `fat_g` are daily totals.
    `sodium_mg`, `fiber_g`, `sugar_g`, `saturated_fat_g`, `cholesterol_mg`,
    `potassium_mg` and every key in `micros` are LOWER BOUNDS — food databases
    record them on only a fraction of entries, so the day sums whichever foods
    happened to carry the field. Nothing in the payload marks them, and a
    plausible-looking value is not evidence of completeness. Never infer a
    deficiency or an excess from one (observed: ~200 mg potassium on a
    2,600 kcal day). Null `water_ml`/`caffeine_mg` means unreported, not zero.

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
      - `expenditure`: energy OUT — `active_kcal_avg` (movement + exercise),
        `basal_kcal_avg` (resting), `tdee_kcal_avg` (their sum), and
        `balance_kcal_avg` (intake minus TDEE), each with its own day count

    Active energy already includes workout burn: TDEE is active + basal, and
    adding `training.energy_kcal` on top double-counts every session. Basal is
    null until the athlete's app build syncs it, in which case TDEE and balance
    are null too and active alone is what you have. Today is excluded from
    expenditure — health metrics have no partial-day flag, so a day in progress
    holds only the hours elapsed.

    Balance is a direction with a magnitude, not a measurement: intake is
    self-reported and skews low, which biases the computed deficit larger, and
    basal is HealthKit's estimate — the two errors compound rather than cancel.
    `body` carries the unmodelled cross-check: `weight_change` (a least-squares
    fit across the readings' span, not last-minus-first), `weight_sd` (the
    scatter it sits in) and `weigh_ins` (how many readings back both).

    Averages cover energy, macros and the rest of the nutrient columns — but
    only `energy_kcal`, `carbs_g`, `protein_g` and `fat_g` are true totals.
    The averages of `sodium_mg`, `fiber_g`, `sugar_g`, `saturated_fat_g`,
    `cholesterol_mg` and `potassium_mg` are averages OF LOWER BOUNDS, because
    food databases record those on only some entries. Never read one as a
    deficiency or an excess; their trends track logging detail as much as diet.

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
