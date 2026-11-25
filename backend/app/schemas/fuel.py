"""Fuelling on the wire: saved products, and what was (or is to be) drunk and
eaten on a workout. camelCase. Volumes in ml, carbohydrates in g, caffeine in
mg, positions in meters into the workout."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

# A drink is logged as one total for the workout; a gel or anything else as
# single items, each at a point in it.
FuelKind = Literal["drink", "gel", "other"]

MAX_ENTRIES = 100


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


def _clean_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("name must not be blank")
    return value


class ProductCreate(_CamelModel):
    name: str = Field(max_length=120)
    kind: FuelKind
    # A drink's serving, which carbsG and caffeineMg are for.
    volume_ml: float | None = Field(default=None, gt=0, le=5_000)
    carbs_g: float | None = Field(default=None, ge=0, le=1_000)
    caffeine_mg: float | None = Field(default=None, ge=0, le=1_000)

    _name = field_validator("name")(_clean_name)


class ProductUpdate(_CamelModel):
    """Only the fields present are changed. `volumeMl`, `carbsG` and
    `caffeineMg` can be sent as null to clear them."""

    name: str | None = Field(default=None, max_length=120)
    kind: FuelKind | None = None
    volume_ml: float | None = Field(default=None, gt=0, le=5_000)
    carbs_g: float | None = Field(default=None, ge=0, le=1_000)
    caffeine_mg: float | None = Field(default=None, ge=0, le=1_000)

    _name = field_validator("name")(_clean_name)


class ProductOut(_CamelModel):
    id: uuid.UUID
    name: str
    kind: str
    volume_ml: float | None
    carbs_g: float | None
    caffeine_mg: float | None
    created_at: datetime


class EntryIn(_CamelModel):
    """One entry. With a `productId`, whatever is left out is filled in from
    the product: its name and kind, and its carbohydrates and caffeine (for a
    drink, in proportion to the volume). Without one, `name` and `kind` are
    required."""

    product_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=120)
    kind: FuelKind | None = None
    volume_ml: float | None = Field(default=None, gt=0, le=20_000)
    carbs_g: float | None = Field(default=None, ge=0, le=2_000)
    caffeine_mg: float | None = Field(default=None, ge=0, le=2_000)
    at_distance: float | None = Field(default=None, ge=0, le=1_000_000)

    _name = field_validator("name")(_clean_name)


class EntriesReplace(_CamelModel):
    entries: list[EntryIn] = Field(max_length=MAX_ENTRIES)


class EntryOut(_CamelModel):
    id: uuid.UUID
    product_id: uuid.UUID | None
    name: str
    kind: str
    volume_ml: float | None
    carbs_g: float | None
    caffeine_mg: float | None
    at_distance: float | None


class FuelSummary(_CamelModel):
    """Totals over a list of entries. An entry without a figure counts as
    zero, so a total is a floor when something was logged without one."""

    volume_ml: float
    carbs_g: float
    caffeine_mg: float
    # Per hour of the workout's duration. Null for a plan (a session has no
    # duration yet) and for a workout too short for the rate to mean much.
    carbs_per_hour_g: float | None = None
    fluid_per_hour_ml: float | None = None


class SessionFuelOut(_CamelModel):
    """The fuelling plan on a planned session."""

    entries: list[EntryOut]
    summary: FuelSummary


class WorkoutFuelOut(_CamelModel):
    """What was taken on a workout, next to what was planned for it."""

    entries: list[EntryOut]
    summary: FuelSummary
    # The plan on the session this workout counts for. Empty when the workout
    # is not linked to a session, or the session has no plan.
    planned: list[EntryOut]
    planned_summary: FuelSummary | None
    planned_session_id: uuid.UUID | None


class FuelHistoryItem(WorkoutFuelOut):
    workout_id: uuid.UUID
    activity_type: str
    start_date: datetime
    duration: float | None
    total_distance: float | None
