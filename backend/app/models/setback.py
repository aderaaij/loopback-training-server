import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Setback(Base):
    """An illness or injury with a start and, once it is over, an end.

    Its own record rather than a reason on a missed run: an athlete can be ill
    on a rest day, and one illness usually spans several runs. Dates are the
    athlete's local calendar days, stored as given.
    """

    __tablename__ = "setback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "illness" or "injury".
    kind: Mapped[str] = mapped_column(String(16))
    # "mild", "moderate" or "severe": the athlete's own call.
    severity: Mapped[str] = mapped_column(String(16), default="moderate", server_default="moderate")
    start_date: Mapped[date] = mapped_column(Date)
    # Last day of the setback. NULL = still going on.
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Injuries only, free text ("left calf").
    body_part: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    checkins: Mapped[list["SetbackCheckin"]] = relationship(
        back_populates="setback",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SetbackCheckin.date",
    )

    __table_args__ = (Index("ix_setback_user_start", "user_id", "start_date"),)


class SetbackCheckin(Base):
    """How the athlete felt on one day of a setback. One per day."""

    __tablename__ = "setback_checkin"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    setback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("setback.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date)
    # "worse", "same", "better" or "fine".
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    setback: Mapped[Setback] = relationship(back_populates="checkins")

    __table_args__ = (UniqueConstraint("setback_id", "date", name="uq_setback_checkin_day"),)
