import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class OAuthAuthorization(Base):
    """One run of the OAuth sign-in an assistant starts to reach the coach.

    A row goes through two stages and is then deleted. It is created when the
    assistant sends someone to /oauth/authorize, and waits for that person to
    approve it in the dashboard (`user_id` and `code_hash` empty). Approving
    fills both in and hands the assistant a one-time code; trading that code
    for a token deletes the row, which is what makes the code single-use.

    `expires_at` covers whichever stage the row is in: the time left to
    approve, then the much shorter time left to trade the code in.
    """

    __tablename__ = "oauth_authorizations"

    # Also the id in the approval page's address. Knowing it grants nothing:
    # approving takes a signed-in athlete.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The address of the client's metadata document (see app/oauth.py).
    client_id: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_challenge: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    # Set together when the athlete approves.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # SHA-256 hex of the code; the code itself is never stored.
    code_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True, index=True)
