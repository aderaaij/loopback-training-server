"""Fetch validation inputs from the DB and run the pure validator.

Scope note: soundness is a property of the athlete's calendar, not of one
plan — runs from two plans still land on the same legs. So the planned
timeline is always the user's full upcoming queue (non-retired, scheduled,
same activity); a target plan only contributes its context (guardrails,
race date) on top.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.plan import SCHEDULED_STATUSES, Plan
from app.models.queue import WorkoutQueue
from app.models.user import User
from app.models.workout import Workout
from app.plan_validation import (
    HistoryRun,
    estimate_easy_speed,
    extract_guardrails,
    extract_race_date,
    session_from_composition,
    validate_schedule,
)
from app.schedule_utils import resolve_sessions

HISTORY_WEEKS = 12


def run_validation(db, user: User, plan: Plan | None = None) -> tuple[list[dict], list[dict]]:
    """Validate the user's upcoming schedule. Returns (warnings, week summaries)."""
    today = datetime.now(timezone.utc).date()
    activity = plan.activity_type if plan else "running"

    history = [
        HistoryRun(date=w.start_date.date(), distance_m=w.total_distance, duration_s=w.duration)
        for w in db.scalars(
            select(Workout).where(
                Workout.user_id == user.id,
                Workout.activity_type == activity,
                Workout.start_date >= datetime.now(timezone.utc) - timedelta(weeks=HISTORY_WEEKS),
            )
        )
    ]
    easy_speed = estimate_easy_speed(history)

    planned = [
        session_from_composition(
            item.workout_data, item.scheduled_date.date(), item.title, easy_speed
        )
        for item in db.scalars(
            select(WorkoutQueue).where(
                WorkoutQueue.user_id == user.id,
                WorkoutQueue.activity_type == activity,
                WorkoutQueue.status.in_(("pending", "fetched", "synced")),
                WorkoutQueue.scheduled_date.is_not(None),
            )
        )
        if item.scheduled_date.date() >= today
    ]

    strength_dates = set()
    for p in db.scalars(
        select(Plan).where(Plan.user_id == user.id, Plan.status.in_(SCHEDULED_STATUSES))
    ):
        for session in resolve_sessions((p.metadata_ or {}).get("schedule")):
            strength_dates.add(session["date"])

    return validate_schedule(
        planned,
        history,
        today=today,
        race_date=extract_race_date(plan.metadata_ if plan else None),
        guardrails=extract_guardrails(plan.metadata_ if plan else None),
        strength_dates=strength_dates,
    )


def owned_plan_or_none(db, user: User, plan_id) -> Plan | None:
    """The plan if it exists and belongs to the user; validation context only,
    so unlike get_owned this never raises."""
    if plan_id is None:
        return None
    plan = db.get(Plan, plan_id)
    return plan if plan is not None and plan.user_id == user.id else None
