import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from app.auth import CurrentUser
from app.database import DbSession
from app.models.inventory import WorkoutInventory
from app.models.queue import WorkoutQueue
from app.schemas.inventory import InventoryItem, InventoryItemRead

router = APIRouter()


@router.put("")
def sync_inventory(items: list[InventoryItem], db: DbSession, user: CurrentUser):
    """Replace this user's stored inventory with their full on-device snapshot."""
    incoming_ids = {item.id for item in items}
    # One timestamp for the whole snapshot: synced_at means "last time the
    # device reported this item", so it must move on update too — an in-place
    # `complete` flip with a stale synced_at made the snapshot look older
    # than the data it carried.
    now = datetime.now(timezone.utc)

    # Delete THIS USER's items no longer on device (never touch other users' rows).
    db.execute(
        delete(WorkoutInventory).where(
            WorkoutInventory.user_id == user.id,
            WorkoutInventory.id.notin_(incoming_ids),
        )
    )

    # Upsert each item
    for item in items:
        existing = db.get(WorkoutInventory, item.id)
        if existing and existing.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Inventory id belongs to another user"
            )
        if existing:
            existing.display_name = item.display_name
            existing.year = item.date.year
            existing.month = item.date.month
            existing.day = item.date.day
            existing.hour = item.date.hour
            existing.minute = item.date.minute
            existing.complete = item.complete
            existing.synced_at = now
        else:
            db.add(WorkoutInventory(
                id=item.id,
                user_id=user.id,
                display_name=item.display_name,
                year=item.date.year,
                month=item.date.month,
                day=item.date.day,
                hour=item.date.hour,
                minute=item.date.minute,
                complete=item.complete,
                synced_at=now,
            ))

    db.commit()
    return {"ok": True, "count": len(items)}


@router.get("", response_model=list[InventoryItemRead])
def get_inventory(db: DbSession, user: CurrentUser):
    """Return the current on-device workout inventory."""
    q = select(WorkoutInventory).where(WorkoutInventory.user_id == user.id).order_by(
        WorkoutInventory.year,
        WorkoutInventory.month,
        WorkoutInventory.day,
        WorkoutInventory.hour,
        WorkoutInventory.minute,
    )
    items = db.scalars(q).all()
    # The device only knows a run as complete when it was started from the
    # watch's schedule. A session the athlete linked a workout to afterwards
    # is completed on the queue item instead, and counts just the same.
    completed_ids = set(
        db.scalars(
            select(WorkoutQueue.id).where(
                WorkoutQueue.user_id == user.id,
                WorkoutQueue.status == "completed",
                WorkoutQueue.id.in_([i.id for i in items]),
            )
        )
    )
    out = [InventoryItemRead.model_validate(i) for i in items]
    for row in out:
        row.complete = row.complete or row.id in completed_ids
    return out
