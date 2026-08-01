import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Kept as a literal rather than imported from app.data_consent: that module
# depends on app.auth, which depends on this one. `test_data_consent.py`
# asserts a freshly created user ends up with exactly DEFAULT_DOMAINS, so the
# duplication cannot drift silently.
_DEFAULT_CONSENT_SQL = "ARRAY['training','recovery','body','activity','nutrition']::text[]"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    # NULL password_hash = login disabled until a password is set (e.g. the
    # seeded bootstrap admin before the first `cli bootstrap`).
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Which categories of health data the coach may read (app/data_consent.py).
    # A text[] rather than five booleans so a new domain needs no migration and
    # an unknown one round-trips harmlessly.
    data_consent: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text(_DEFAULT_CONSENT_SQL)
    )
    # Two stamps on purpose: the app re-reports on every launch, so `reported`
    # answers "is this athlete's app still telling us?" (NULL = never has) while
    # `updated` answers "when did the choice last change?".
    data_consent_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_consent_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tokens: Mapped[list["ApiToken"]] = relationship(  # noqa: F821
        "ApiToken", back_populates="user", cascade="all, delete-orphan"
    )
