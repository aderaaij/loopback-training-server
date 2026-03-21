from datetime import datetime

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.database import DbSession
from app.models.feedback import WorkoutFeedback
from app.schemas.feedback import FeedbackCreate, FeedbackRead

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
def submit_feedback(payload: FeedbackCreate, db: DbSession):
    """Record feedback for a missed workout. Idempotent upsert by workout_id."""
    values = {
        "id": payload.id,
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
    update_fields = {k: v for k, v in values.items() if k not in ("id", "workout_id")}
    stmt = insert(WorkoutFeedback).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_workout_feedback_workout_id",
        set_=update_fields,
    )
    db.execute(stmt)
    db.commit()
    return {"ok": True, "id": str(payload.id)}


@router.get("", response_model=list[FeedbackRead])
def get_feedback(
    db: DbSession,
    since: datetime | None = Query(default=None, description="Only entries with scheduledDate on or after this date"),
    limit: int = Query(default=20, ge=1, le=100),
    action: str | None = Query(default=None, description="Filter by action: move, adjust, or skip"),
):
    """Retrieve feedback history, newest first."""
    q = select(WorkoutFeedback).order_by(WorkoutFeedback.scheduled_date.desc())

    if since is not None:
        q = q.where(WorkoutFeedback.scheduled_date >= since)
    if action is not None:
        q = q.where(WorkoutFeedback.action == action)

    q = q.limit(limit)
    return db.scalars(q).all()
