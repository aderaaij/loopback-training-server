import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.plan import PlanRead


# "feedback" is written by the plan-completion flow and may also be authored
# directly (the MCP's append_plan_note advertises it).
NOTE_KINDS = ("decision", "preference", "constraint", "life_context", "observation", "blocker", "feedback")
_KIND_PATTERN = rf"^({'|'.join(NOTE_KINDS)})$"


class PlanNoteCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: str = Field(pattern=_KIND_PATTERN)
    summary: str = Field(min_length=1, max_length=280)
    body: str | None = None
    importance: int = Field(default=2, ge=1, le=3)
    conversation_id: str | None = Field(default=None, alias="conversationId", max_length=64)
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    plan_id: uuid.UUID | None = Field(default=None, alias="planId")


class PlanNoteUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: str | None = Field(default=None, pattern=_KIND_PATTERN)
    summary: str | None = Field(default=None, min_length=1, max_length=280)
    body: str | None = None
    importance: int | None = Field(default=None, ge=1, le=3)
    expires_at: datetime | None = Field(default=None, alias="expiresAt")


class PlanNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    plan_id: uuid.UUID | None = Field(serialization_alias="planId")
    kind: str
    summary: str
    body: str | None
    importance: int
    conversation_id: str | None = Field(serialization_alias="conversationId")
    expires_at: datetime | None = Field(serialization_alias="expiresAt")
    created_at: datetime
    updated_at: datetime


class PlanContext(BaseModel):
    """Aggregated continuity context for an LLM conversation."""

    plan: PlanRead | None
    notes: list[PlanNoteRead]
    last_note_age_days: int | None
    continuity_hint: str
    # The athlete's display units ("metric" / "imperial"; null = never chosen)
    # and what the coach should do about them. Here rather than in the MCP's
    # instructions because those are fixed per server, not per athlete, and
    # this is the one call the coach makes at the start of every conversation.
    units: str | None = None
    units_hint: str = ""
