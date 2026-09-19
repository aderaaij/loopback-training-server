from datetime import datetime, timezone

from fastapi import APIRouter, Query, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from app.auth import CurrentUser
from app.database import DbSession
from app.models.feedback import WorkoutFeedback
from app.models.queue import WorkoutQueue
from app.schemas.feedback import FeedbackCreate, FeedbackRead

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
def submit_feedback(payload: FeedbackCreate, db: DbSession, user: CurrentUser):
    """Record feedback for a missed workout. Idempotent upsert per (user, workout_id)."""
    values = {
        "id": payload.id,
        "user_id": user.id,
        "workout_id": payload.workout_id,
        "workout_name": payload.workout_name,
        "scheduled_date": payload.scheduled_date,
        "detected_at": payload.detected_at,
        "acknowledged_at": payload.acknowledged_at,
        "reason": payload.reason,
        "reason_note": payload.reason_note,
        "action": payload.action,
        "new_date": payload.new_date,
        "dismissed": payload.dismissed,
    }
    update_fields = {k: v for k, v in values.items() if k not in ("id", "user_id", "workout_id")}
    stmt = insert(WorkoutFeedback).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_workout_feedback_user_workout",
        set_=update_fields,
    )
    db.execute(stmt)

    # A skip is a decision about the queued workout itself: retire the queue
    # item (workout_id IS the queue item id — the app-facing GET injects it)
    # so the watch stops being offered a run that was skipped. One-way, and a
    # completed item is never downgraded.
    if payload.action == "skip" and not payload.dismissed:
        db.execute(
            update(WorkoutQueue)
            .where(
                WorkoutQueue.id == payload.workout_id,
                WorkoutQueue.user_id == user.id,
                WorkoutQueue.status.notin_(("completed", "skipped")),
            )
            .values(status="skipped")
        )

    # A move is the athlete re-dating the run on their watch (the app does
    # that locally before sending this). Carry the new date onto the queue
    # item, or every server view of the schedule keeps the old day, including
    # /workouts/queue/scheduled, which a fresh install restores the watch from.
    if payload.action == "move" and payload.new_date is not None and not payload.dismissed:
        item = db.get(WorkoutQueue, payload.workout_id)
        if item is not None and item.user_id == user.id and item.status not in ("completed", "skipped"):
            new_date = payload.new_date if payload.new_date.tzinfo else payload.new_date.replace(tzinfo=timezone.utc)
            item.scheduled_date = new_date
            # The composition's own date is what the app schedules from.
            # Whole seconds with a Z: the app's ISO 8601 decoder rejects
            # fractional seconds.
            item.workout_data = {
                **(item.workout_data or {}),
                "scheduledDate": new_date.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }

    db.commit()
    return {"ok": True, "id": str(payload.id)}


@router.get("", response_model=list[FeedbackRead])
def get_feedback(
    db: DbSession,
    user: CurrentUser,
    since: datetime | None = Query(default=None, description="Only entries with scheduledDate on or after this date"),
    limit: int = Query(default=20, ge=1, le=100),
    action: str | None = Query(default=None, description="Filter by action: move, adjust, or skip"),
):
    """Retrieve feedback history, newest first."""
    q = select(WorkoutFeedback).where(WorkoutFeedback.user_id == user.id).order_by(WorkoutFeedback.scheduled_date.desc())

    if since is not None:
        q = q.where(WorkoutFeedback.scheduled_date >= since)
    if action is not None:
        q = q.where(WorkoutFeedback.action == action)

    q = q.limit(limit)
    return db.scalars(q).all()
