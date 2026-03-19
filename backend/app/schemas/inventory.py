import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InventoryDate(BaseModel):
    year: int
    month: int
    day: int
    hour: int
    minute: int


class InventoryItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: uuid.UUID
    display_name: str = Field(alias="displayName")
    date: InventoryDate
    complete: bool = False


class InventoryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    year: int | None
    month: int | None
    day: int | None
    hour: int | None
    minute: int | None
    complete: bool
    synced_at: datetime
