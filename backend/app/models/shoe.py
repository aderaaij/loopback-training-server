import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Shoe(Base):
    """A pair of running shoes. Its mileage is never stored: it is
    `start_distance` plus the distance of the workouts that point at it."""

    __tablename__ = "shoe"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    # Meters already on the pair when it was added (carried over from another
    # tracker, or simply runs from before it was here).
    start_distance: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    # Meters the athlete expects the pair to last. NULL = no target.
    target_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The pair new runs are assigned to. At most one per user (index below).
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("uq_shoe_one_default_per_user", "user_id", unique=True, postgresql_where=text("is_default")),
    )
