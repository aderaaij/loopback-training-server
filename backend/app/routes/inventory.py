import uuid

from fastapi import APIRouter
from sqlalchemy import delete, select

from app.database import DbSession
from app.models.inventory import WorkoutInventory
from app.schemas.inventory import InventoryItem, InventoryItemRead

router = APIRouter()


@router.put("")
def sync_inventory(items: list[InventoryItem], db: DbSession):
    """Replace the stored inventory with the full on-device snapshot."""
    incoming_ids = {item.id for item in items}

    # Delete items no longer on device
    db.execute(delete(WorkoutInventory).where(WorkoutInventory.id.notin_(incoming_ids)))

    # Upsert each item
    for item in items:
        existing = db.get(WorkoutInventory, item.id)
        if existing:
            existing.display_name = item.display_name
            existing.year = item.date.year
            existing.month = item.date.month
            existing.day = item.date.day
            existing.hour = item.date.hour
            existing.minute = item.date.minute
            existing.complete = item.complete
        else:
            db.add(WorkoutInventory(
                id=item.id,
                display_name=item.display_name,
                year=item.date.year,
                month=item.date.month,
                day=item.date.day,
                hour=item.date.hour,
                minute=item.date.minute,
                complete=item.complete,
            ))

    db.commit()
    return {"ok": True, "count": len(items)}


@router.get("", response_model=list[InventoryItemRead])
def get_inventory(db: DbSession):
    """Return the current on-device workout inventory."""
    q = select(WorkoutInventory).order_by(
        WorkoutInventory.year,
        WorkoutInventory.month,
        WorkoutInventory.day,
        WorkoutInventory.hour,
        WorkoutInventory.minute,
    )
    return db.scalars(q).all()
