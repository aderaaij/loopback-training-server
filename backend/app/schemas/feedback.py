import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    workout_id: uuid.UUID = Field(alias="workoutId")
    workout_name: str = Field(alias="workoutName")
    scheduled_date: datetime = Field(alias="scheduledDate")
    detected_at: datetime = Field(alias="detectedAt")
    acknowledged_at: datetime | None = Field(default=None, alias="acknowledgedAt")
    reason: Literal["busy", "tired", "weather", "soreness", "motivation", "other"]
    reason_note: str | None = Field(default=None, alias="reasonNote")
    action: Literal["move", "adjust", "skip"]
    new_date: datetime | None = Field(default=None, alias="newDate")
    dismissed: bool


class FeedbackRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    workout_id: uuid.UUID = Field(serialization_alias="workoutId")
    workout_name: str = Field(serialization_alias="workoutName")
    scheduled_date: datetime = Field(serialization_alias="scheduledDate")
    detected_at: datetime = Field(serialization_alias="detectedAt")
    acknowledged_at: datetime | None = Field(serialization_alias="acknowledgedAt")
    reason: str
    reason_note: str | None = Field(serialization_alias="reasonNote")
    action: str
    new_date: datetime | None = Field(serialization_alias="newDate")
    dismissed: bool
