"""Setbacks (illness and injury) on the wire. camelCase, dates as YYYY-MM-DD."""

import uuid
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

SetbackKind = Literal["illness", "injury"]
SetbackSeverity = Literal["mild", "moderate", "severe"]
CheckinStatus = Literal["worse", "same", "better", "fine"]


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class SetbackCreate(_CamelModel):
    # The client may name the row, so a retried create cannot make a second one.
    id: uuid.UUID | None = None
    kind: SetbackKind
    severity: SetbackSeverity = "moderate"
    start_date: date
    end_date: date | None = None
    body_part: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)

    _clean = field_validator("body_part", "note")(_blank_to_none)

    @model_validator(mode="after")
    def _ordered(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("endDate must not be before startDate")
        return self


class SetbackUpdate(_CamelModel):
    """Only the fields present are changed. `endDate: null` reopens a setback;
    `bodyPart: null` and `note: null` clear them."""

    kind: SetbackKind | None = None
    severity: SetbackSeverity | None = None
    start_date: date | None = None
    end_date: date | None = None
    body_part: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)

    _clean = field_validator("body_part", "note")(_blank_to_none)


class CheckinUpsert(_CamelModel):
    status: CheckinStatus
    note: str | None = Field(default=None, max_length=2000)

    _clean = field_validator("note")(_blank_to_none)


class CheckinOut(_CamelModel):
    date: date
    status: str
    note: str | None


class RecoveryMetricOut(_CamelModel):
    # Column name on the daily metrics, e.g. "resting_heart_rate".
    metric: str
    label: str
    unit: str
    # Median over the four weeks before the setback.
    usual: float
    # How far from usual still counts as normal.
    tolerance: float
    latest: float | None
    latest_date: date | None
    # latest minus usual; null without a recent reading.
    difference: float | None
    # "normal", "off" or "no_recent_data".
    state: str


class RecoveryOut(_CamelModel):
    """Whether an open setback looks over. A suggestion: the athlete decides.
    See app/setback_recovery.py for the rules."""

    # "looks_recovered", "not_yet" or "insufficient_data".
    status: str
    # What the status rests on: "metrics", "status" (the athlete's daily
    # check-ins) or null.
    basis: str | None
    # One or two sentences, readable by the athlete and the coach alike.
    summary: str
    metrics: list[RecoveryMetricOut]


class SetbackOut(_CamelModel):
    id: uuid.UUID
    kind: str
    severity: str
    start_date: date
    end_date: date | None
    body_part: str | None
    note: str | None
    # No end date yet.
    active: bool
    # Days from the start through the end, or through today (UTC) while it is
    # still going on. Both ends count: one sick day is 1.
    days: int
    checkins: list[CheckinOut]
    # Open setbacks only; null once it has an end date.
    recovery: RecoveryOut | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, setback, today: date | None = None, recovery: RecoveryOut | None = None) -> "SetbackOut":
        today = today or datetime.now(timezone.utc).date()
        last = setback.end_date or max(today, setback.start_date)
        return cls(
            id=setback.id,
            kind=setback.kind,
            severity=setback.severity,
            start_date=setback.start_date,
            end_date=setback.end_date,
            body_part=setback.body_part,
            note=setback.note,
            active=setback.end_date is None,
            days=(last - setback.start_date).days + 1,
            checkins=[CheckinOut.model_validate(c) for c in setback.checkins],
            recovery=recovery,
            created_at=setback.created_at,
            updated_at=setback.updated_at,
        )
