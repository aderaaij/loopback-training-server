"""add week-start preference to users

The dashboard calendar always started its weeks on Monday. Athletes who read
calendars Sunday-first can now choose, and the choice is stored on the user
like the units preference, so it follows them across browsers.

NULL means "never chosen" and reads as Monday, so existing rows stay NULL and
existing installs look exactly as before.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c5d6e7f8a9'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("week_start", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("week_start_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "week_start_updated_at")
    op.drop_column("users", "week_start")
