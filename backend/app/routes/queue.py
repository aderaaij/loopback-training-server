import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.auth import CurrentUser
from app.database import DbSession
from app.models.queue import WorkoutQueue
from app.schemas.queue import (
    QueueBatchCreatedResponse,
    QueueItemCreate,
    QueueItemCreatedRead,
    QueueItemRead,
    QueueItemUpdate,
    QueueStatusUpdate,
)
from app.tenancy import get_owned
from app.validation_service import owned_plan_or_none, run_validation

router = APIRouter()


def _scheduled_date_from_data(workout_data: dict | None) -> datetime | None:
    """Parse scheduledDate out of a workout composition, if present."""
    raw = (workout_data or {}).get("scheduledDate")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("/pending", response_model=list[QueueItemRead])
def get_pending(db: DbSession, user: CurrentUser):
    q = (
        select(WorkoutQueue)
        .where(WorkoutQueue.user_id == user.id, WorkoutQueue.status == "pending")
        .order_by(WorkoutQueue.created_at)
    )
    return db.scalars(q).all()


@router.get("", response_model=list[QueueItemRead])
def list_queue(
    db: DbSession,
    user: CurrentUser,
    queue_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    q = select(WorkoutQueue).where(WorkoutQueue.user_id == user.id).order_by(WorkoutQueue.created_at.desc())

    if queue_status:
        q = q.where(WorkoutQueue.status == queue_status)

    q = q.offset(offset).limit(limit)
    return db.scalars(q).all()


@router.post("", response_model=QueueItemCreatedRead, status_code=status.HTTP_201_CREATED)
def create_queue_item(payload: QueueItemCreate, db: DbSession, user: CurrentUser):
    item = WorkoutQueue(
        user_id=user.id,
        activity_type=payload.activity_type,
        title=payload.title,
        description=payload.description,
        workout_data=payload.workout_data,
        plan_id=payload.plan_id,
        scheduled_date=payload.scheduled_date or _scheduled_date_from_data(payload.workout_data),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    warnings, _ = run_validation(db, user, owned_plan_or_none(db, user, item.plan_id))
    out = QueueItemCreatedRead.model_validate(item)
    out.validation = warnings
    return out


@router.post("/batch", response_model=QueueBatchCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_queue_items_batch(payload: list[QueueItemCreate], db: DbSession, user: CurrentUser):
    items = []
    for p in payload:
        item = WorkoutQueue(
            user_id=user.id,
            activity_type=p.activity_type,
            title=p.title,
            description=p.description,
            workout_data=p.workout_data,
            plan_id=p.plan_id,
            scheduled_date=p.scheduled_date or _scheduled_date_from_data(p.workout_data),
        )
        db.add(item)
        items.append(item)
    db.commit()
    for item in items:
        db.refresh(item)

    plan_ids = {i.plan_id for i in items if i.plan_id is not None}
    plan = owned_plan_or_none(db, user, plan_ids.pop()) if len(plan_ids) == 1 else None
    warnings, _ = run_validation(db, user, plan)
    return QueueBatchCreatedResponse(
        items=[QueueItemRead.model_validate(i) for i in items],
        validation=warnings,
    )


@router.patch("/{item_id}", response_model=QueueItemRead)
def update_queue_item(item_id: uuid.UUID, payload: QueueItemUpdate, db: DbSession, user: CurrentUser):
    item = get_owned(db, WorkoutQueue, item_id, user)

    if payload.activity_type is not None:
        item.activity_type = payload.activity_type
    if payload.title is not None:
        item.title = payload.title
    if payload.description is not None:
        item.description = payload.description
    if payload.workout_data is not None:
        item.workout_data = payload.workout_data
        item.scheduled_date = _scheduled_date_from_data(payload.workout_data)
    if payload.scheduled_date is not None:
        item.scheduled_date = payload.scheduled_date
    if payload.plan_id is not None:
        item.plan_id = payload.plan_id

    db.commit()
    db.refresh(item)
    return item


@router.patch("/{item_id}/status", response_model=QueueItemRead)
def update_queue_status(item_id: uuid.UUID, payload: QueueStatusUpdate, db: DbSession, user: CurrentUser):
    item = get_owned(db, WorkoutQueue, item_id, user)

    now = datetime.now(timezone.utc)
    item.status = payload.status

    if payload.status == "fetched" and item.fetched_at is None:
        item.fetched_at = now
    elif payload.status == "completed" and item.completed_at is None:
        item.completed_at = now

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_queue_item(item_id: uuid.UUID, db: DbSession, user: CurrentUser):
    item = get_owned(db, WorkoutQueue, item_id, user)
    db.delete(item)
    db.commit()


# App-facing router: GET /api/workouts/queue returns pending items,
# DELETE /api/workouts/queue/{id} removes them.
workout_queue_router = APIRouter()


def _as_composition(item: WorkoutQueue) -> dict:
    """An item's workout_data with the queue item's id injected, so the app
    can decode it as a QueuedWorkoutComposition."""
    composition = dict(item.workout_data or {})
    # Use the queue item's ID so the app can DELETE /api/workouts/queue/{id}
    composition["id"] = str(item.id)
    return composition


@workout_queue_router.get("")
def app_get_pending(db: DbSession, user: CurrentUser):
    """Return pending queue items as workout compositions for the iOS app.

    Each item's workout_data is returned directly with the queue item's
    id injected, so the app can decode QueuedWorkoutComposition objects.
    """
    q = (
        select(WorkoutQueue)
        .where(WorkoutQueue.user_id == user.id, WorkoutQueue.status == "pending")
        .order_by(WorkoutQueue.created_at)
    )
    return [_as_composition(item) for item in db.scalars(q).all()]


@workout_queue_router.get("/scheduled")
def app_get_scheduled(
    db: DbSession,
    user: CurrentUser,
    from_: datetime = Query(alias="from", description="Earliest scheduled date to include: the device's local start of today"),
):
    """Delivered items that are still due, as compositions (same shape as the
    pending endpoint), ordered by scheduled date.

    `synced` is per account, not per device: once one install confirms an
    item, the pending endpoint never offers it again, so a reinstall or a new
    phone starts with an empty watch schedule. The app diffs this list against
    its WorkoutKit schedule and re-schedules whatever is missing, without
    confirming anything again. Completed and skipped items are excluded, which
    is what keeps a coach delete (acked → skipped) from coming back.
    """
    q = (
        select(WorkoutQueue)
        .where(
            WorkoutQueue.user_id == user.id,
            WorkoutQueue.status.in_(("fetched", "synced")),
            WorkoutQueue.scheduled_date >= from_,
        )
        .order_by(WorkoutQueue.scheduled_date)
    )
    return [_as_composition(item) for item in db.scalars(q).all()]


@workout_queue_router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def app_mark_queue_item_synced(item_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """Mark a queue item as synced to Apple Watch (previously deleted it)."""
    item = get_owned(db, WorkoutQueue, item_id, user)
    item.status = "synced"
    item.fetched_at = item.fetched_at or datetime.now(timezone.utc)
    db.commit()


@workout_queue_router.patch("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def app_mark_queue_item_synced_patch(item_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """PATCH variant of the sync confirmation — newer app builds send this.

    No body is parsed: whatever the app sends, a confirmed install means
    `synced`. Statuses past `synced` (completed/skipped) are never downgraded.
    """
    item = get_owned(db, WorkoutQueue, item_id, user)
    if item.status in ("pending", "fetched"):
        item.status = "synced"
        item.fetched_at = item.fetched_at or datetime.now(timezone.utc)
        db.commit()
