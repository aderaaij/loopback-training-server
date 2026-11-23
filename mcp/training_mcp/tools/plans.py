"""MCP tools for managing training plans."""

import logging
from typing import Any

from fastmcp import FastMCP

from training_mcp.schemas import JsonTolerant, PlanStatus, WeeklyDays
from training_mcp.services.api_client import client
from training_mcp.wire import text_result

logger = logging.getLogger(__name__)

plans_router = FastMCP(name="Plan Tools")


@plans_router.tool
@text_result
async def create_plan(
    name: str,
    activity_type: str,
    start_date: str,
    end_date: str | None = None,
    description: str | None = None,
    metadata: JsonTolerant[dict[str, Any] | None] = None,
    status: PlanStatus | None = None,
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
        status: Defaults to "active" — the block being run right now. Pass
            "upcoming" for a plan built ahead of its start date: it stays out
            of "which plan am I on" answers, while its sessions still appear
            in the calendar and schedule checks so the new block can be
            validated before it starts. Only one plan per activity should be
            active at a time; if one is already running, the next block is
            "upcoming" until the athlete starts it.

    Returns:
        The created plan with its id.
    """
    try:
        body: dict[str, Any] = {
            "name": name,
            "activityType": activity_type,
            "startDate": start_date,
        }
        if status is not None:
            body["status"] = status
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
@text_result
async def get_plan(plan_id: str) -> dict | list:
    """Get a training plan by ID, including its metadata.

    Args:
        plan_id: UUID of the plan.

    Returns:
        Plan object with name, activity_type, status, dates, description,
        metadata, plus two computed fields:
        - progress: session counts (total/completed/skipped/remaining) —
          queued Apple Watch runs, plus scheduled strength sessions for plans
          with a recurring schedule. A strength session counts as completed
          when a synced Hevy workout landed on its date, skipped when the
          date passed with no match, remaining otherwise. (The runs_* field
          names predate strength support; they count sessions of either kind.)
        - finishable: true when an active plan looks done (window passed, or
          every session retired with ≥1 completed and no end date still
          ahead — a plan queued a week at a time is not done each time its
          queue runs empty). Nothing auto-completes;
          if true, offer the athlete a wrap-up (complete_plan on the dashboard
          or update_plan status="completed").
    """
    try:
        return await client.get_plan(plan_id)
    except Exception as e:
        logger.exception(f"Error in get_plan: {e}")
        return {"error": str(e)}


@plans_router.tool
@text_result
async def list_plans(
    status: PlanStatus | None = None,
    activity_type: str | None = None,
) -> dict | list:
    """List training plans.

    Args:
        status: Filter by status — "active", "upcoming", "completed",
            "archived" or "abandoned". "upcoming" is a block built ahead of
            its start date: its sessions still show in the calendar and
            schedule checks, but it is not the plan the athlete is on.
        activity_type: Filter by activity type (e.g. "running").

    Returns:
        List of plans, newest first. Each carries computed `progress` and
        `finishable` — see get_plan for their semantics (progress counts
        queued runs and scheduled strength sessions alike; finishable=true
        means offer a wrap-up).
    """
    try:
        return await client.list_plans(status=status, activity_type=activity_type)
    except Exception as e:
        logger.exception(f"Error in list_plans: {e}")
        return {"error": str(e)}


@plans_router.tool
@text_result
async def update_plan(
    plan_id: str,
    name: str | None = None,
    status: PlanStatus | None = None,
    description: str | None = None,
    metadata: JsonTolerant[dict[str, Any] | None] = None,
    end_date: str | None = None,
) -> dict | list:
    """Update a training plan.

    Common uses: mark as completed/abandoned, start an upcoming block,
    update metadata, adjust dates.

    Args:
        plan_id: UUID of the plan.
        name: New plan name.
        status: New status — "active", "upcoming", "completed", "archived"
            or "abandoned". Nothing promotes a plan on its start date, so
            starting an upcoming block is an explicit
            update_plan(status="active").
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
@text_result
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
@text_result
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

    Only for an athlete who lifts on fixed weekdays. One who fits strength
    around the rest of the week has no "every Tuesday": give them individual
    sessions with `add_strength_session` instead, and skip this tool. The two
    also combine: a weekly pattern, with `move_strength_session` or
    `remove_strength_session` for the weeks that differ.

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
@text_result
async def add_strength_session(
    plan_id: str,
    date: str,
    title: str,
    routine_id: str | None = None,
) -> dict | list:
    """Put one strength session on one date, leaving the rest of the plan's
    schedule as it is.

    This is how to schedule strength for an athlete without fixed gym days:
    look at the week's runs with `get_training_calendar`, then add each
    session on the day it fits. It also adds an extra session next to a weekly
    pattern. A plan needs no weekly pattern at all; the first session added
    starts its schedule.

    Like every strength session it is a plan marker, not a watch workout, and
    it counts as done when a Hevy workout syncs in on that date. Adding the
    same title on the same date again replaces it.

    Args:
        plan_id: UUID of the strength plan (create_plan with activity_type
            "strength").
        date: The day of the session (YYYY-MM-DD).
        title: What the session is, e.g. "Lower body + core".
        routine_id: Optional Hevy routine id (from the hevy-mcp).

    Returns:
        The resolved schedule: dated `sessions` (`recurring` is false for
        individual ones, each with a `conflict` flag) and `warnings` for run
        collisions.
    """
    try:
        session: dict[str, Any] = {"date": date, "title": title}
        if routine_id is not None:
            session["routineId"] = routine_id
        return await client.add_plan_schedule_session(plan_id, session)
    except Exception as e:
        logger.exception(f"Error in add_strength_session: {e}")
        return {"error": str(e)}


@plans_router.tool
@text_result
async def move_strength_session(plan_id: str, date: str, to_date: str) -> dict | list:
    """Move the strength session on one date to another date, keeping its
    title and routine.

    Works for an individual session and for one occurrence of a weekly
    pattern; the pattern's other weeks stay where they are. Use it when the
    athlete says a session doesn't fit that day this week.

    Args:
        plan_id: UUID of the strength plan.
        date: The day the session is on now (YYYY-MM-DD).
        to_date: The day to move it to (YYYY-MM-DD).

    Returns:
        The resolved schedule after the move. An error when nothing is
        scheduled on `date`.
    """
    try:
        return await client.move_plan_schedule_session(plan_id, date, to_date)
    except Exception as e:
        logger.exception(f"Error in move_strength_session: {e}")
        return {"error": str(e)}


@plans_router.tool
@text_result
async def remove_strength_session(plan_id: str, date: str) -> dict | list:
    """Take the strength session on one date off the plan.

    An individual session is removed. One occurrence of a weekly pattern is
    skipped for that date only and the pattern carries on. To drop the whole
    schedule use `clear_plan_schedule`.

    Args:
        plan_id: UUID of the strength plan.
        date: The day of the session to remove (YYYY-MM-DD).

    Returns:
        The resolved schedule after the removal. An error when nothing is
        scheduled on `date`.
    """
    try:
        return await client.remove_plan_schedule_session(plan_id, date)
    except Exception as e:
        logger.exception(f"Error in remove_strength_session: {e}")
        return {"error": str(e)}


@plans_router.tool
@text_result
async def get_plan_schedule(plan_id: str) -> dict | list:
    """Get a plan's schedule (weekly pattern and individual sessions) expanded
    into concrete dated sessions.

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
@text_result
async def clear_plan_schedule(plan_id: str) -> dict | list:
    """Remove a plan's whole schedule: the weekly pattern and every individual
    session. For a single session use `remove_strength_session`.

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
@text_result
async def validate_plan(plan_id: str) -> dict | list:
    """Deterministically check the athlete's upcoming schedule for soundness,
    using this plan's context (guardrails, race date from metadata).

    Run this after queueing or reshuffling a plan's workouts, and before
    presenting a plan to the athlete as final. It is pure arithmetic over the
    queue + the athlete's real workout history — no LLM judgment — checking
    the coaching playbook's numeric invariants: weekly ramp vs the actual
    4-week baseline, missing down weeks, long-run share, back-to-back hard
    days, taper shape before `race_date`, and the plan's own declared
    guardrails.

    Interpreting results: `critical` warnings should be resolved (adjust the
    schedule and re-queue) or explicitly signed off by the athlete; `warn`
    items should at least be mentioned; `info` is context. `estimated: true`
    means the numbers rest on a pace assumption (time-based steps without a
    pace alert). Warnings never block anything.

    Note `strength_collision` (info) fires for a hard run the day *after* a
    strength session — an interference heads-up, deliberately broader than
    the calendar's `conflict` flag, which only marks two sessions sharing a
    date. A day-after warning here with conflict=false on the calendar is
    consistent, not contradictory.

    Args:
        plan_id: UUID of the plan whose context (guardrails, race date)
            frames the check. The schedule itself is always the athlete's
            full upcoming queue — runs from other plans count too.

    Returns:
        {plan_id, warnings[], weeks[]} — warnings have {code, severity,
        message, week, data, estimated}; weeks summarize each planned week
        (planned_km, actual_km, total_km, run_days, hard_days, longest_km,
        baseline_km, ratio).
    """
    try:
        return await client.validate_plan(plan_id)
    except Exception as e:
        logger.exception(f"Error in validate_plan: {e}")
        return {"error": str(e)}


@plans_router.tool
@text_result
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
        completed, conflict. `conflict` marks same-day double-bookings only;
        adjacent-day concerns (hard run right after a strength day) surface
        through validate_plan instead.
    """
    try:
        return await client.get_training_calendar(date_from=date_from, date_to=date_to)
    except Exception as e:
        logger.exception(f"Error in get_training_calendar: {e}")
        return {"error": str(e)}
