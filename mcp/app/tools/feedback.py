"""MCP tools for accessing workout feedback data."""

import logging

from fastmcp import FastMCP

from app.schemas import FeedbackAction
from app.services.api_client import client
from app.wire import text_result

logger = logging.getLogger(__name__)

feedback_router = FastMCP(name="Feedback Tools")


@feedback_router.tool
@text_result
async def get_workout_feedback(
    since: str | None = None,
    limit: int = 20,
    action: FeedbackAction | None = None,
) -> dict | list:
    """
    Retrieve the athlete's check-ins on runs they missed or changed ahead of time.

    Use this to understand patterns in missed workouts and inform coaching decisions.
    Query action="adjust" to find workouts the user flagged for plan adjustment.

    An entry acknowledged on or before its scheduled day (acknowledgedAt's date
    not after scheduledDate's) was filed ahead of time: the athlete moved or
    skipped the run before it lapsed. That is a plan change, not a miss. A
    missed-run check-in is always filed on a later day. A skip with reason "other" and a note like
    "Made room for <run>" was cleared off the day another run moved onto.

    Args:
        since: Only return entries with scheduledDate on or after this date (ISO 8601, e.g. "2026-03-01").
        limit: Max entries to return (default 20).
        action: Filter by action type: "move", "adjust", or "skip".

    Returns:
        List of feedback entries, each with: id, workoutId, workoutName, scheduledDate,
        detectedAt, acknowledgedAt, reason, reasonNote, action, newDate, dismissed.
    """
    try:
        return await client.get_feedback(since=since, limit=limit, action=action)
    except Exception as e:
        logger.exception(f"Error in get_workout_feedback: {e}")
        return {"error": str(e)}


@feedback_router.tool
@text_result
async def get_missed_workouts() -> dict | list:
    """
    Get currently past-due, incomplete workouts not yet checked in for their current day.

    This is a convenience tool that cross-references the on-device workout inventory
    with existing feedback to find workouts that are overdue and haven't been addressed.
    A run that was moved and then also went past its new day counts as missed again.

    Returns:
        List of missed workouts, each with: workoutId, displayName, scheduledDate, daysMissed.
    """
    try:
        return await client.get_missed_workouts()
    except Exception as e:
        logger.exception(f"Error in get_missed_workouts: {e}")
        return {"error": str(e)}
