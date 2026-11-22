import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, func, text
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
    # True once the athlete has linked or unlinked this workout by hand. From
    # then on plan_workout_id is theirs: an upload no longer writes it.
    plan_link_manual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # The pair worn. Deleting the pair keeps the workout and clears this.
    shoe_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shoe.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Set once someone picked, changed or took off the pair by hand. False
    # means shoe_id is still whatever the automatic default made it.
    shoe_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    effort_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    estimated_effort_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1), nullable=True)
    # Heart rate (bpm) as the workout ended, and one and two minutes later.
    # The drop between them is the recovery figure. All null when the watch
    # recorded nothing usable after the end.
    end_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    heart_rate_after_1min: Mapped[float | None] = mapped_column(Float, nullable=True)
    heart_rate_after_2min: Mapped[float | None] = mapped_column(Float, nullable=True)
    # The VO2 max estimate (mL/kg/min) Health recorded for this workout. A
    # `body` figure under data consent, like the daily one.
    vo2_max: Mapped[float | None] = mapped_column(Float, nullable=True)
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
