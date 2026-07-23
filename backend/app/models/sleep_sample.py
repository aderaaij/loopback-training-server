import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# HealthKit sleepAnalysis values, snake_cased. `unspecified` is
# HKCategoryValueSleepAnalysis.asleepUnspecified; `in_bed` is bed occupancy,
# stored for future use (sleep efficiency) but never counted as sleep.
SLEEP_STAGES = ("rem", "core", "deep", "awake", "unspecified", "in_bed")


class SleepSample(Base):
    """A raw HealthKit sleep sample as shipped by the app.

    Append-only: identity is the full (user, span, stage, source) tuple so
    re-posting the same window is idempotent. The daily rollup in
    daily_health_metrics is *derived* from these rows (app/sleep_merge.py),
    never authored by clients once samples exist.
    """

    __tablename__ = "sleep_samples"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "start_at", "end_at", "stage", "source", name="uq_sleep_samples_identity"),
        Index("ix_sleep_samples_user_span", "user_id", "end_at", "start_at"),
        CheckConstraint("end_at > start_at", name="sleep_sample_span_positive"),
        CheckConstraint(
            "stage IN ('rem', 'core', 'deep', 'awake', 'unspecified', 'in_bed')",
            name="sleep_sample_stage_valid",
        ),
    )
