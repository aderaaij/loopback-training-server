"""add oauth_authorizations (sign-in runs for assistants connecting to the coach)

An assistant that connects to /mcp through OAuth sends the athlete to the
server to approve it, and gets a one-time code back that it trades for a
token. One row holds one such run, from the request to the trade, and is
deleted when the code is used. The token it ends in is an ordinary
`api_tokens` row, so nothing else changes.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f8a9b0c1d2e3'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_authorizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text(), nullable=True),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("code_challenge", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_oauth_authorizations_expires_at", "oauth_authorizations", ["expires_at"])
    op.create_index("ix_oauth_authorizations_code_hash", "oauth_authorizations", ["code_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_oauth_authorizations_code_hash", table_name="oauth_authorizations")
    op.drop_index("ix_oauth_authorizations_expires_at", table_name="oauth_authorizations")
    op.drop_table("oauth_authorizations")
