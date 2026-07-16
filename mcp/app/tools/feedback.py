"""MCP tools for accessing workout feedback data."""

import logging

from fastmcp import FastMCP

from app.schemas import FeedbackAction
from app.services.api_client import client

logger = logging.getLogger(__name__)

feedback_router = FastMCP(name="Feedback Tools")


@feedback_router.tool
async def get_workout_feedback(
    since: str | None = None,
    limit: int = 20,
    action: FeedbackAction | None = None,
) -> dict | list:
    """
    Retrieve feedback entries for missed workouts.

    Use this to understand patterns in missed workouts and inform coaching decisions.
    Query action="adjust" to find workouts the user flagged for plan adjustment.

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
async def get_missed_workouts() -> dict | list:
    """
    Get currently past-due, incomplete workouts that don't yet have feedback entries.

    This is a convenience tool that cross-references the on-device workout inventory
    with existing feedback to find workouts that are overdue and haven't been addressed.

    Returns:
        List of missed workouts, each with: workoutId, displayName, scheduledDate, daysMissed.
    """
    try:
        return await client.get_missed_workouts()
    except Exception as e:
        logger.exception(f"Error in get_missed_workouts: {e}")
        return {"error": str(e)}
