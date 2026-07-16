"""MCP tools for managing training plans."""

import logging
from typing import Any

from fastmcp import FastMCP

from app.schemas import PlanStatus, WeeklyDays
from app.services.api_client import client

logger = logging.getLogger(__name__)

plans_router = FastMCP(name="Plan Tools")


@plans_router.tool
async def create_plan(
    name: str,
    activity_type: str,
    start_date: str,
    end_date: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict | list:
    """Create a new training plan.

    Call this before batch_create_workouts to get a plan_id that links
    all queued workouts together.

    Args:
        name: Plan name (e.g. "Slow Burn 8-Week Return").
        activity_type: Primary activity (e.g. "running", "cycling").
        start_date: Plan start date (YYYY-MM-DD).
        end_date: Plan end date (YYYY-MM-DD), or null if open-ended.
        description: High-level what and why.
        metadata: Flexible JSON object for goals, guardrails, phases,
            athlete context, etc. No required keys. Example:
            {
                "goals": [{"type": "weekly_volume", "target": 32, "unit": "km", "by_week": 8}],
                "guardrails": ["Miss a run: don't make it up"],
                "phases": [{"name": "Base", "weeks": [1, 2], "volume_target_km": 18}],
                "athlete_context": {"fitness_level": "Detrained"}
            }

    Returns:
        The created plan with its id.
    """
    try:
        body: dict[str, Any] = {
            "name": name,
            "activityType": activity_type,
            "startDate": start_date,
        }
        if end_date is not None:
            body["endDate"] = end_date
        if description is not None:
            body["description"] = description
        if metadata is not None:
            body["metadata"] = metadata
        return await client.create_plan(body)
    except Exception as e:
        logger.exception(f"Error in create_plan: {e}")
        return {"error": str(e)}


@plans_router.tool
async def get_plan(plan_id: str) -> dict | list:
    """Get a training plan by ID, including its metadata.

    Args:
        plan_id: UUID of the plan.

    Returns:
        Plan object with name, activity_type, status, dates, description, metadata.
    """
    try:
        return await client.get_plan(plan_id)
    except Exception as e:
        logger.exception(f"Error in get_plan: {e}")
        return {"error": str(e)}


@plans_router.tool
async def list_plans(
    status: PlanStatus | None = None,
    activity_type: str | None = None,
) -> dict | list:
    """List training plans.

    Args:
        status: Filter by status — "active", "completed", or "abandoned".
        activity_type: Filter by activity type (e.g. "running").

    Returns:
        List of plans, newest first.
    """
    try:
        return await client.list_plans(status=status, activity_type=activity_type)
    except Exception as e:
        logger.exception(f"Error in list_plans: {e}")
        return {"error": str(e)}


@plans_router.tool
async def update_plan(
    plan_id: str,
    name: str | None = None,
    status: PlanStatus | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
    end_date: str | None = None,
) -> dict | list:
    """Update a training plan.

    Common uses: mark as completed/abandoned, update metadata, adjust dates.

    Args:
        plan_id: UUID of the plan.
        name: New plan name.
        status: New status — "active", "completed", or "abandoned".
        description: Updated description.
        metadata: Replacement metadata object (replaces entire metadata, not merged).
        end_date: New end date (YYYY-MM-DD).

    Returns:
        The updated plan.
    """
    try:
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if status is not None:
            updates["status"] = status
        if description is not None:
            updates["description"] = description
        if metadata is not None:
            updates["metadata"] = metadata
        if end_date is not None:
            updates["endDate"] = end_date
        return await client.update_plan(plan_id, updates)
    except Exception as e:
        logger.exception(f"Error in update_plan: {e}")
        return {"error": str(e)}


@plans_router.tool
async def get_plan_workouts(plan_id: str) -> dict | list:
    """Get all queued workouts belonging to a plan.

    Args:
        plan_id: UUID of the plan.

    Returns:
        List of queued workouts for this plan.
    """
    try:
        return await client.get_plan_workouts(plan_id)
    except Exception as e:
        logger.exception(f"Error in get_plan_workouts: {e}")
        return {"error": str(e)}


@plans_router.tool
async def set_strength_schedule(
    plan_id: str,
    start_date: str,
    weeks: int,
    days: WeeklyDays,
    time: str | None = None,
    timezone: str | None = None,
) -> dict | list:
    """Set a recurring weekly schedule on a plan — which routine runs on which
    weekday, for a number of weeks.

    Use this for strength / Hevy cycles: the schedule references Hevy routines
    by id + title (get them from the hevy-mcp first). These sessions are plan
    markers only — they are NOT pushed to the Apple Watch (that's for running
    interval workouts). Completed strength sessions auto-match by date via the
    HealthKit `traditionalStrength` workouts that Hevy already syncs in.

    IMPORTANT — avoid conflicts: call `get_training_calendar` first to see
    scheduled runs, and place strength days on free weekdays. The response also
    returns a `warnings` list flagging any day where a strength session lands on
    the same date as a scheduled run (surfaced, not blocked — you decide).

    Args:
        plan_id: UUID of the plan this cycle belongs to (create one first via
            create_plan with activity_type "strength").
        start_date: First week's anchor date (YYYY-MM-DD).
        weeks: How many weeks the cycle runs (1–52).
        days: Which weekday gets which routine — set only the days that have
            a session. Example:
            {
                "mon": {"title": "Lower", "routineId": "hevy-abc"},
                "wed": {"title": "Upper Push", "routineId": "hevy-def"},
                "fri": {"title": "Deadlifts + Pull", "routineId": "hevy-ghi"}
            }
        time: Optional default time of day "HH:MM".
        timezone: Optional IANA timezone (e.g. "Europe/Lisbon").

    Returns:
        The resolved schedule: concrete dated `sessions` (each with a `conflict`
        flag) and a `warnings` list for run collisions.
    """
    try:
        schedule: dict[str, Any] = {
            "startDate": start_date,
            "weeks": weeks,
            "days": days.model_dump(exclude_none=True),
        }
        if time is not None:
            schedule["time"] = time
        if timezone is not None:
            schedule["timezone"] = timezone
        return await client.set_plan_schedule(plan_id, schedule)
    except Exception as e:
        logger.exception(f"Error in set_strength_schedule: {e}")
        return {"error": str(e)}


@plans_router.tool
async def get_plan_schedule(plan_id: str) -> dict | list:
    """Get a plan's recurring schedule expanded into concrete dated sessions.

    Args:
        plan_id: UUID of the plan.

    Returns:
        {plan_id, schedule, sessions[], warnings[]} — sessions carry a
        `conflict` flag where they collide with a queued run.
    """
    try:
        return await client.get_plan_schedule(plan_id)
    except Exception as e:
        logger.exception(f"Error in get_plan_schedule: {e}")
        return {"error": str(e)}


@plans_router.tool
async def clear_plan_schedule(plan_id: str) -> dict | list:
    """Remove a plan's recurring weekly schedule.

    Args:
        plan_id: UUID of the plan.

    Returns:
        The plan's now-empty schedule response.
    """
    try:
        return await client.clear_plan_schedule(plan_id)
    except Exception as e:
        logger.exception(f"Error in clear_plan_schedule: {e}")
        return {"error": str(e)}


@plans_router.tool
async def get_training_calendar(
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict | list:
    """Get the unified training calendar: scheduled runs (Apple Watch queue)
    merged with recurring strength sessions (from active plan schedules), with
    same-day conflicts flagged.

    Call this before scheduling strength days so you can place them on days that
    don't already have a run.

    Args:
        date_from: Window start (YYYY-MM-DD). Defaults to today.
        date_to: Window end (YYYY-MM-DD). Defaults to today + 28 days.

    Returns:
        {from, to, entries[]} where each entry has: date, kind ("run" or
        "strength"), title, activityType, status, planId, planName, routineId,
        completed, conflict.
    """
    try:
        return await client.get_training_calendar(date_from=date_from, date_to=date_to)
    except Exception as e:
        logger.exception(f"Error in get_training_calendar: {e}")
        return {"error": str(e)}
