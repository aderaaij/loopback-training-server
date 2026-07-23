from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Stage = Literal["rem", "core", "deep", "awake", "unspecified", "in_bed"]


def parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown IANA timezone: {name!r}") from exc


class SleepSampleIn(BaseModel):
    start: datetime
    end: datetime
    stage: Stage
    source: str = Field(min_length=1, max_length=255)

    @field_validator("start", "end")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must carry a UTC offset")
        return v

    @model_validator(mode="after")
    def _positive_span(self) -> "SleepSampleIn":
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self


class SleepSamplesBulkCreate(BaseModel):
    # The client's IANA timezone — needed to place noon-to-noon night windows.
    timezone: str
    samples: list[SleepSampleIn] = Field(min_length=1, max_length=20000)

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        parse_timezone(v)
        return v


class SleepSamplesBulkResponse(BaseModel):
    received: int
    stored: int
    days_updated: list[date]


class SleepSampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    start_at: datetime
    end_at: datetime
    stage: str
    source: str


class SleepRederiveRequest(BaseModel):
    start_date: date
    end_date: date
    timezone: str

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        parse_timezone(v)
        return v

    @model_validator(mode="after")
    def _ordered(self) -> "SleepRederiveRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class SleepRederiveResponse(BaseModel):
    days_updated: list[date]
