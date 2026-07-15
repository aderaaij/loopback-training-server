import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Workout(Base):
    __tablename__ = "workout"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    activity_type: Mapped[str] = mapped_column(String(100), index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_distance: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_energy_burned: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plan_workout_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    effort_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    estimated_effort_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_workout_activity_start", "activity_type", "start_date"),
        CheckConstraint(
            "effort_score IS NULL OR (effort_score BETWEEN 1 AND 10)",
            name="effort_score_range",
        ),
        CheckConstraint(
            "estimated_effort_score IS NULL OR (estimated_effort_score BETWEEN 1 AND 10)",
            name="estimated_effort_score_range",
        ),
    )
