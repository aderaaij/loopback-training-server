import uuid
from datetime import date, datetime

from sqlalchemy import Date, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyHealthMetrics(Base):
    __tablename__ = "daily_health_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    sleep_duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_stages: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    resting_heart_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_sdnn: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    vo2_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_energy_burned: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_percentage: Mapped[float | None] = mapped_column(Float, nullable=True)
    lean_body_mass: Mapped[float | None] = mapped_column(Float, nullable=True)
    respiratory_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    spo2: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_health_metrics_user_date"),
    )
