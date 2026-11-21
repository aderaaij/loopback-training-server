import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


_KNOWN_FIELDS = {
    "id", "activityType", "startDate", "endDate",
    "duration", "totalDistance", "totalEnergyBurned", "source", "data",
    "planWorkoutId", "effortScore", "estimatedEffortScore",
}


class WorkoutCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    activity_type: str = Field(alias="activityType")
    start_date: datetime = Field(alias="startDate")
    end_date: datetime = Field(alias="endDate")
    duration: float | None = None
    total_distance: float | None = Field(default=None, alias="totalDistance")
    total_energy_burned: float | None = Field(default=None, alias="totalEnergyBurned")
    source: str | None = None
    plan_workout_id: uuid.UUID | None = Field(default=None, alias="planWorkoutId")
    effort_score: float | None = Field(default=None, alias="effortScore", ge=1, le=10)
    estimated_effort_score: float | None = Field(default=None, alias="estimatedEffortScore", ge=1, le=10)
    data: dict = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def collect_extra_into_data(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Collect any extra top-level keys (splits, heartRate, etc.) into data."""
        data = values.get("data", {})
        extra_keys = set(values.keys()) - _KNOWN_FIELDS
        if extra_keys:
            if not isinstance(data, dict):
                data = {}
            for key in extra_keys:
                data[key] = values.pop(key)
            values["data"] = data
        return values


class WorkoutRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_type: str
    start_date: datetime
    end_date: datetime
    duration: float | None
    total_distance: float | None
    total_energy_burned: float | None
    source: str | None
    plan_workout_id: uuid.UUID | None
    plan_link_manual: bool = False
    shoe_id: uuid.UUID | None = None
    shoe_confirmed: bool = False
    effort_score: float | None
    estimated_effort_score: float | None
    data: dict
    created_at: datetime
    updated_at: datetime


class WorkoutList(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_type: str
    start_date: datetime
    end_date: datetime
    duration: float | None
    total_distance: float | None
    total_energy_burned: float | None
    source: str | None
    plan_workout_id: uuid.UUID | None
    plan_link_manual: bool = False
    shoe_id: uuid.UUID | None = None
    shoe_confirmed: bool = False
    effort_score: float | None
    estimated_effort_score: float | None
    created_at: datetime


class WorkoutShoeUpdate(BaseModel):
    """Body of PUT /api/workouts/{id}/shoe. `shoeId: null` takes the pair off."""

    model_config = ConfigDict(populate_by_name=True)

    shoe_id: uuid.UUID | None = Field(alias="shoeId")


class WorkoutPlanLinkUpdate(BaseModel):
    """Body of PUT /api/workouts/{id}/plan-link. `planWorkoutId: null` unlinks."""

    model_config = ConfigDict(populate_by_name=True)

    plan_workout_id: uuid.UUID | None = Field(alias="planWorkoutId")


class WorkoutContextQueueItem(BaseModel):
    """Queue-item embed for the context endpoint. Includes the workout_data
    composition so consumers can render planned-vs-actual without a second
    queue lookup."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    activity_type: str
    status: str
    scheduled_date: datetime | None
    plan_id: uuid.UUID | None
    workout_data: dict | None
    completed_at: datetime | None


class WorkoutContextPlan(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    activity_type: str
    status: str
    start_date: date
    end_date: date | None


class WorkoutContextFeedback(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    reason: str
    reason_note: str | None
    action: str
    new_date: datetime | None
    scheduled_date: datetime
    dismissed: bool
    created_at: datetime


class WorkoutContextRead(BaseModel):
    workout_id: uuid.UUID
    plan_workout_id: uuid.UUID | None
    # The athlete linked (or unlinked) this workout by hand, so the session it
    # points at may not be the one it was recorded against, or the same kind.
    plan_link_manual: bool = False
    queue_item: WorkoutContextQueueItem | None
    plan: WorkoutContextPlan | None
    feedback: WorkoutContextFeedback | None


class WorkoutSummary(BaseModel):
    period: str
    activity_type: str | None
    count: int
    total_distance: float | None
    total_duration: float | None
    avg_distance: float | None
    avg_duration: float | None
    total_energy_burned: float | None
