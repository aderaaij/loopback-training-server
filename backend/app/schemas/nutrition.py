from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.nutrition import CLEARABLE_COLUMNS


class NutritionCreate(BaseModel):
    """One day of dietary totals. Every nutrient is optional — a food logger
    that only records energy and macros simply omits the rest, and omitted
    fields never overwrite what is already stored.

    To retract something already stored, name it in `clear`: omission means
    "no opinion", `clear` means "known absent". A client that stops reporting
    a field has no other way to say so."""

    model_config = ConfigDict(populate_by_name=True)

    date: date
    energy_kcal: float | None = Field(default=None, alias="energyKcal")
    carbs_g: float | None = Field(default=None, alias="carbsG")
    protein_g: float | None = Field(default=None, alias="proteinG")
    fat_g: float | None = Field(default=None, alias="fatG")
    saturated_fat_g: float | None = Field(default=None, alias="saturatedFatG")
    fiber_g: float | None = Field(default=None, alias="fiberG")
    sugar_g: float | None = Field(default=None, alias="sugarG")
    sodium_mg: float | None = Field(default=None, alias="sodiumMg")
    potassium_mg: float | None = Field(default=None, alias="potassiumMg")
    cholesterol_mg: float | None = Field(default=None, alias="cholesterolMg")
    water_ml: float | None = Field(default=None, alias="waterMl")
    caffeine_mg: float | None = Field(default=None, alias="caffeineMg")
    micros: dict[str, float] | None = None
    entry_count: int | None = Field(default=None, alias="entryCount")
    sources: list[str] | None = None
    partial: bool | None = None
    clear: list[str] | None = None

    @model_validator(mode="after")
    def _validate_clear(self):
        if not self.clear:
            return self
        unknown = sorted(set(self.clear) - CLEARABLE_COLUMNS)
        if unknown:
            raise ValueError(
                f"clear names unknown or non-clearable field(s): {', '.join(unknown)}"
            )
        # Naming a field in `clear` while also sending a value for it is a
        # client bug, and guessing which one wins would silently drop data.
        conflicting = sorted(f for f in self.clear if getattr(self, f, None) is not None)
        if conflicting:
            raise ValueError(
                f"field(s) both provided and cleared: {', '.join(conflicting)}"
            )
        return self


class NutritionBulkCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    days: list[NutritionCreate]


class NutritionBulkResponse(BaseModel):
    upserted: int


class NutritionDeleteResponse(BaseModel):
    date: date
    deleted: int


class NutritionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: date
    energy_kcal: float | None
    carbs_g: float | None
    protein_g: float | None
    fat_g: float | None
    saturated_fat_g: float | None
    fiber_g: float | None
    sugar_g: float | None
    sodium_mg: float | None
    potassium_mg: float | None
    cholesterol_mg: float | None
    water_ml: float | None
    caffeine_mg: float | None
    micros: dict | None
    entry_count: int | None
    sources: list | None
    partial: bool
    created_at: datetime
    updated_at: datetime


class NutritionPeriodBody(BaseModel):
    """Body-composition context for the period, from daily_health_metrics."""

    weight_avg: float | None = None
    weight_start: float | None = None
    weight_end: float | None = None
    weight_change: float | None = None


class NutritionPeriodTraining(BaseModel):
    """Training load for the period, from recorded workouts."""

    workouts: int = 0
    distance_km: float | None = None
    duration_min: float | None = None
    energy_kcal: float | None = None


class NutritionPeriod(BaseModel):
    period_start: date
    period_end: date
    days_logged: int
    days_partial: int
    days_in_period: int
    nutrition: dict[str, float | None]
    protein_g_per_kg: float | None = None
    body: NutritionPeriodBody
    training: NutritionPeriodTraining


class NutritionSummary(BaseModel):
    period: str
    start_date: date
    end_date: date
    periods: list[NutritionPeriod]
