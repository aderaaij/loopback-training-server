import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# The nutrient columns, in the order they read best in a payload. Shared by the
# upsert, the read schema and the period summariser so a new nutrient is added
# in exactly one place.
NUTRIENT_COLUMNS: tuple[str, ...] = (
    "energy_kcal",
    "carbs_g",
    "protein_g",
    "fat_g",
    "saturated_fat_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
    "potassium_mg",
    "cholesterol_mg",
    "water_ml",
    "caffeine_mg",
)

# Everything an upsert may carry beyond the identity (user_id, date).
UPSERT_COLUMNS: tuple[str, ...] = NUTRIENT_COLUMNS + ("micros", "entry_count", "sources", "partial")


class DailyNutrition(Base):
    """Daily dietary totals synced from HealthKit.

    Kept out of daily_health_metrics on purpose: the provenance differs (food
    logging apps write these, not the watch), coverage is sparse by nature —
    days without logging simply have no row — and the health-metrics payload
    stays lean for the LLM and the recovery charts that read it.

    The core nutrients get real columns; anything else the app cares to ship
    lands in `micros` (JSONB) so a new nutrient needs no migration.
    """

    __tablename__ = "daily_nutrition"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)

    energy_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    protein_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    saturated_fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fiber_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sugar_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    sodium_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    potassium_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    cholesterol_mg: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_ml: Mapped[float | None] = mapped_column(Float, nullable=True)
    caffeine_mg: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Long-tail nutrients (iron, calcium, magnesium, vitamins…) keyed by name.
    micros: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # How many HealthKit entries fed this day, and which apps wrote them —
    # logging adherence is itself a signal when reading a diet trend.
    entry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # True when the day was still in progress at sync time. Averages exclude
    # these: a half-logged today would drag every mean down.
    partial: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_daily_nutrition_user_date"),
    )
