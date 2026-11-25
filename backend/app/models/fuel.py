import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class FuelProduct(Base):
    """Something the athlete drinks or eats on a run, saved once so logging
    it is a pick rather than typing the label again: a gel, a drink mix."""

    __tablename__ = "fuel_product"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    # "drink", "gel" or "other". A drink is logged as a total for the workout,
    # the rest as single items at a point in it.
    kind: Mapped[str] = mapped_column(String(20))
    # A drink's serving in ml, which the two figures below are for (a 500 ml
    # bottle with 40 g of carbohydrates). NULL for anything that is not a drink.
    volume_ml: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per serving of a drink, per piece of anything else. NULL = not stated.
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    caffeine_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FuelEntry(Base):
    """One thing drunk or eaten, or planned to be.

    It belongs to exactly one of two things: a recorded workout, where it is
    what was taken, or a planned session (a queue item), where it is the
    plan. A workout's plan is read through its `plan_workout_id`.

    The name and figures are copied from the product when the entry is made,
    so changing or deleting a product leaves what was logged as it was.
    """

    __tablename__ = "fuel_entry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout.id", ondelete="CASCADE"), nullable=True, index=True
    )
    queue_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_queue.id", ondelete="CASCADE"), nullable=True, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_product.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    # For a drink: the total drunk over the workout, in ml.
    volume_ml: Mapped[float | None] = mapped_column(Float, nullable=True)
    # In this entry as a whole, not per serving.
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    caffeine_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Meters into the workout it was taken at. NULL for a drink, and for
    # anything the athlete did not place.
    at_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Order within its list, as sent.
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("(workout_id IS NULL) <> (queue_item_id IS NULL)", name="ck_fuel_entry_one_owner"),
    )
