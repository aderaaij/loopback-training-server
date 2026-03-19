import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QueueItemCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    activity_type: str = Field(alias="activityType")
    title: str
    description: str | None = None
    workout_data: dict | None = Field(default=None, alias="workoutData")


class QueueItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    activity_type: str
    title: str
    description: str | None
    workout_data: dict | None
    status: str
    created_at: datetime
    fetched_at: datetime | None
    completed_at: datetime | None


class QueueItemUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    activity_type: str | None = Field(default=None, alias="activityType")
    title: str | None = None
    description: str | None = None
    workout_data: dict | None = Field(default=None, alias="workoutData")


class QueueStatusUpdate(BaseModel):
    status: str
