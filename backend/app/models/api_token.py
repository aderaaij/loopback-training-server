import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.token_scope import FULL


class ApiToken(Base):
    __tablename__ = "api_tokens"
    # In the model as well as the migration: the test schema is built from the
    # models, and a value the tests accept must be one the database accepts.
    __table_args__ = (CheckConstraint("scope IN ('full', 'coach')", name="ck_api_tokens_scope"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # SHA-256 hex of the token; the raw token is never stored.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Last client User-Agent seen on this token (e.g. "Loopback-iOS/1.0") —
    # the server half of the app version handshake: answers "which devices
    # still run an old app" before shipping a breaking change.
    last_user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL = long-lived (device tokens); dashboard cookies get a finite expiry.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # `full` is the athlete; `coach` is held to what the coach's tools call
    # (app/token_scope.py). Tokens from before the column are `full`.
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default=FULL, server_default=FULL)

    user: Mapped["User"] = relationship("User", back_populates="tokens")  # noqa: F821
