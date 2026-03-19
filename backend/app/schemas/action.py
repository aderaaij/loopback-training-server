import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ActionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    workout_id: uuid.UUID = Field(alias="workoutId")
    action: Literal["edit", "delete"]
    composition: dict | None = None


class ActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    workout_id: uuid.UUID = Field(serialization_alias="workoutId")
    action: str
    composition: dict | None
    created_at: datetime
