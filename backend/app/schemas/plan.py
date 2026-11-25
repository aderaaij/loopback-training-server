import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class PlanCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    activity_type: str = Field(alias="activityType")
    status: str = "active"
    start_date: date = Field(alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanProgress(BaseModel):
    """Session counts: queued runs plus, for plans with a recurring schedule,
    scheduled strength sessions (completed = a strength workout synced in on
    the session's date; skipped = the date passed unmatched). The runs_*
    names predate strength support and count sessions of either kind."""

    runs_total: int = 0
    runs_completed: int = 0
    runs_skipped: int = 0
    runs_remaining: int = 0


class PlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    name: str
    activity_type: str
    status: str
    start_date: date
    end_date: date | None
    description: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
    # Computed on every response that returns a plan. `finishable` = active
    # plan that looks done — the dashboard offers the celebrate-and-complete
    # flow; nothing flips status by itself. Create/update used to skip this and
    # return the defaults, which made `finishable: false` a plausible-looking
    # lie rather than an honest absence: same plan, same second, `get` said
    # true. `progress: None` at least reads as "not computed".
    progress: PlanProgress | None = None
    finishable: bool = False


class PlanCompleteRequest(BaseModel):
    feedback: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


class PlanCompleteResponse(BaseModel):
    plan: PlanRead
    # Another already-active plan of the same activity, if one exists — the UI
    # uses its absence to nudge "set up the next block with your coach".
    next_plan: PlanRead | None = None


class PlanUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    activity_type: str | None = Field(default=None, alias="activityType")
    status: str | None = None
    start_date: date | None = Field(default=None, alias="startDate")
    end_date: date | None = Field(default=None, alias="endDate")
    description: str | None = None
    metadata: dict[str, Any] | None = None


# --- Weekly schedule (recurring cadence stored on plan.metadata.schedule) ---


class ScheduleRoutineRef(BaseModel):
    """A single weekday slot in a recurring schedule.

    ``routine_id`` is an opaque reference to an external routine (e.g. a Hevy
    routine id, looked up by the LLM via the hevy-mcp); this API never resolves
    it. Strength slots do not become Apple Watch compositions.
    """

    model_config = ConfigDict(populate_by_name=True)

    title: str
    routine_id: str | None = Field(default=None, alias="routineId")


class ScheduleSession(BaseModel):
    """One strength session on its own date, outside any weekly pattern."""

    model_config = ConfigDict(populate_by_name=True)

    date: date
    title: str = Field(min_length=1, max_length=200)
    routine_id: str | None = Field(default=None, alias="routineId")


class ScheduleSessionMove(BaseModel):
    to: date


class PlanSchedule(BaseModel):
    """When a strength plan's sessions happen: a weekly recurrence (which
    routine on which weekday, for N weeks), individual dated sessions, or both.

    ``skip_dates`` takes single occurrences out of the weekly recurrence, which
    is how one week's session is dropped or moved without touching the rest.
    """

    model_config = ConfigDict(populate_by_name=True)

    start_date: date | None = Field(default=None, alias="startDate")
    weeks: int | None = Field(default=None, ge=1, le=52)
    days: dict[str, ScheduleRoutineRef] = Field(default_factory=dict)
    sessions: list[ScheduleSession] = Field(default_factory=list)
    skip_dates: list[date] = Field(default_factory=list, alias="skipDates")
    time: str | None = None  # optional "HH:MM" default time of day
    timezone: str | None = None

    @field_validator("days")
    @classmethod
    def _validate_weekdays(cls, v: dict[str, ScheduleRoutineRef]) -> dict[str, ScheduleRoutineRef]:
        bad = [k for k in v if k not in WEEKDAYS]
        if bad:
            raise ValueError(f"invalid weekday keys {bad}; use {list(WEEKDAYS)}")
        return v

    @model_validator(mode="after")
    def _has_something_to_schedule(self):
        if not self.days and not self.sessions:
            raise ValueError("schedule must define at least one weekday or one dated session")
        if self.days and (self.start_date is None or self.weeks is None):
            raise ValueError("a weekly schedule needs startDate and weeks")
        return self


class ScheduledSession(BaseModel):
    """One materialised occurrence of a schedule, with run-conflict info."""

    model_config = ConfigDict(populate_by_name=True)

    date: date
    weekday: str
    title: str
    routine_id: str | None = Field(default=None, serialization_alias="routineId")
    # False for an individual dated session, True for a weekly occurrence.
    recurring: bool = True
    conflict: bool = False
    conflicts_with: list[str] = Field(default_factory=list, serialization_alias="conflictsWith")


class PlanScheduleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    plan_id: uuid.UUID = Field(serialization_alias="planId")
    schedule: PlanSchedule | None
    sessions: list[ScheduledSession] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
