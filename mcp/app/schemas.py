"""Typed workout-composition models (WorkoutKit wire format).

Single source of truth for what a queued workout can express. Two jobs:

1. FastMCP renders these into the tool input schemas, so the LLM can *see*
   every supported option (goals, per-step alerts incl. heart-rate zones)
   instead of having to mine docstring prose.
2. Compositions are validated at the tool boundary before landing in the
   backend's opaque JSONB (the backend stores workout_data verbatim and the
   iOS app decodes it — nothing downstream validates).

Field names are camelCase wherever the wire format is camelCase; workout_data
is served to the iOS app exactly as stored, so do not "normalize" the casing.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

ActivityType = Literal["running", "cycling", "walking", "hiking", "swimming"]
Location = Literal["outdoor", "indoor"]

# Queue lifecycle. The backend stores this column unvalidated and the watch
# endpoints / calendar filter on exact values, so the tool boundary is the
# only guard against a typo orphaning an item.
QueueStatus = Literal["pending", "fetched", "synced", "completed", "skipped"]

# Plan status is also stored unvalidated; the dashboard branches on "active".
PlanStatus = Literal["active", "completed", "abandoned"]

# Enforced by the backend (regex / Literal / Query pattern) — mirrored here so
# the values are visible in the tool schema instead of costing a 422 round trip.
NoteKind = Literal["decision", "preference", "constraint", "life_context", "observation", "blocker"]
FeedbackAction = Literal["move", "adjust", "skip"]
SummaryPeriod = Literal["week", "month", "year"]


def _validate_iso_datetime(v: str) -> str:
    # Validate but return the original string untouched: the iOS app decodes
    # scheduledDate as stored, so we must not rewrite "Z" to "+00:00". The
    # backend silently nulls unparseable dates (item drops off the calendar),
    # which is why this is checked here.
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f'not a valid ISO 8601 datetime (expected e.g. "2026-03-18T07:00:00Z"): {v!r}')
    return v


IsoDateTime = Annotated[str, AfterValidator(_validate_iso_datetime)]


# --- Goals: what defines completion of a step ---------------------------------


class DistanceGoal(BaseModel):
    """Complete the step after covering a distance."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["distance"]
    value: float = Field(gt=0)
    unit: Literal["meters", "kilometers", "miles"]


class TimeGoal(BaseModel):
    """Complete the step after an elapsed duration."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["time"]
    value: float = Field(gt=0)
    unit: Literal["seconds", "minutes"]


class EnergyGoal(BaseModel):
    """Complete the step after burning an energy amount."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["energy"]
    value: float = Field(gt=0)
    unit: Literal["kilocalories"] = "kilocalories"


class OpenGoal(BaseModel):
    """No target — the step runs until the user advances it on the watch."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["open"]


Goal = Annotated[
    DistanceGoal | TimeGoal | EnergyGoal | OpenGoal,
    Field(discriminator="type"),
]


# --- Alerts: the effort target the watch coaches against ----------------------


class _RangeAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: float = Field(gt=0)
    max: float = Field(gt=0)

    @model_validator(mode="after")
    def _check_range(self) -> "_RangeAlert":
        if self.max < self.min:
            raise ValueError("alert max must be >= min")
        return self


class SpeedAlert(_RangeAlert):
    """Speed/pace range — the watch displays and alerts on pace."""

    type: Literal["speed"]
    unit: Literal["metersPerSecond", "kilometersPerHour"]


class HeartRateAlert(_RangeAlert):
    """Explicit heart-rate range in BPM."""

    type: Literal["heartRate"]


class HeartRateZoneAlert(BaseModel):
    """Heart-rate zone 1-5, resolved on the watch against the user's personal zones."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["heartRateZone"]
    zone: int = Field(ge=1, le=5)


class CadenceAlert(_RangeAlert):
    """Cadence range in steps per minute."""

    type: Literal["cadence"]


class PowerAlert(_RangeAlert):
    """Running/cycling power range in watts."""

    type: Literal["power"]


class PowerZoneAlert(BaseModel):
    """Power zone (cycling power zones as configured on the watch)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["powerZone"]
    zone: int = Field(ge=1)


Alert = Annotated[
    SpeedAlert | HeartRateAlert | HeartRateZoneAlert | CadenceAlert | PowerAlert | PowerZoneAlert,
    Field(discriminator="type"),
]


# --- Steps, blocks, and the full composition -----------------------------------


class WorkoutStep(BaseModel):
    """A single step: a goal plus an optional effort alert (WorkoutKit allows one alert per step)."""

    model_config = ConfigDict(extra="forbid")

    goal: Goal
    alert: Alert | None = Field(
        default=None,
        description="Optional effort target for this step: speed/pace, heart rate, HR zone, cadence, or power.",
    )


class IntervalStep(WorkoutStep):
    """One step inside an interval block."""

    purpose: Literal["work", "recovery"]


class IntervalBlock(BaseModel):
    """A repeatable group of interval steps (e.g. 6 x [400m work + 400m recovery])."""

    model_config = ConfigDict(extra="forbid")

    iterations: int = Field(ge=1, description="How many times to repeat this block's steps.")
    steps: list[IntervalStep] = Field(min_length=1)


def dump_step(step: WorkoutStep | None) -> dict | None:
    return step.model_dump(exclude_none=True) if step is not None else None


class WorkoutComposition(BaseModel):
    """Full structured workout in the wire format the iOS app decodes (camelCase keys)."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, description="Unique UUID. Omit to have one generated.")
    displayName: str = Field(description="Name shown on Apple Watch.")
    activityType: ActivityType
    location: Location
    scheduledDate: IsoDateTime = Field(description='ISO 8601, e.g. "2026-03-18T07:00:00Z".')
    blocks: list[IntervalBlock] = Field(min_length=1)
    warmup: WorkoutStep | None = None
    cooldown: WorkoutStep | None = None

    def wire_dict(self) -> dict:
        """Serialize to the exact JSON shape stored in workout_data."""
        return {
            "id": self.id,
            "displayName": self.displayName,
            "activityType": self.activityType,
            "location": self.location,
            "scheduledDate": self.scheduledDate,
            "blocks": [b.model_dump(exclude_none=True) for b in self.blocks],
            "warmup": dump_step(self.warmup),
            "cooldown": dump_step(self.cooldown),
        }


class BatchWorkoutItem(BaseModel):
    """One workout in a batch_create_workouts call."""

    model_config = ConfigDict(extra="forbid")

    activityType: ActivityType
    title: str = Field(description="Display name for the queue item.")
    description: str | None = None
    planId: str | None = Field(default=None, description="UUID of the training plan this workout belongs to.")
    workoutData: WorkoutComposition


class WorkoutActionItem(BaseModel):
    """One edit/delete action in a batch_actions call."""

    model_config = ConfigDict(extra="forbid")

    workoutId: str = Field(description="UUID of the workout on the Apple Watch.")
    action: Literal["edit", "delete"]
    composition: WorkoutComposition | None = Field(
        default=None,
        description="Required for edit (the full replacement workout), omit for delete.",
    )

    @model_validator(mode="after")
    def _edit_needs_composition(self) -> "WorkoutActionItem":
        if self.action == "edit":
            if self.composition is None:
                raise ValueError("composition is required for edit actions")
            if self.composition.id is not None and self.composition.id != self.workoutId:
                raise ValueError("composition.id must match workoutId")
        return self


# --- Recurring weekly schedule (strength / Hevy cycles on a plan) --------------


class ScheduleDaySlot(BaseModel):
    """One weekday's session — a reference to an external routine (e.g. a Hevy routine)."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(description='Session title shown on the calendar (e.g. "Lower", "Upper Push").')
    routineId: str | None = Field(default=None, description="Opaque routine id from hevy-mcp, or null.")


class WeeklyDays(BaseModel):
    """Which weekdays have a session. Set only the days that do; at least one."""

    model_config = ConfigDict(extra="forbid")

    mon: ScheduleDaySlot | None = None
    tue: ScheduleDaySlot | None = None
    wed: ScheduleDaySlot | None = None
    thu: ScheduleDaySlot | None = None
    fri: ScheduleDaySlot | None = None
    sat: ScheduleDaySlot | None = None
    sun: ScheduleDaySlot | None = None

    @model_validator(mode="after")
    def _at_least_one(self) -> "WeeklyDays":
        if not any((self.mon, self.tue, self.wed, self.thu, self.fri, self.sat, self.sun)):
            raise ValueError("schedule must set at least one weekday")
        return self
