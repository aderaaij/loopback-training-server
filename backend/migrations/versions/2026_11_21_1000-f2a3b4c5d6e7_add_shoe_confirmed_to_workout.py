"""add shoe_confirmed to workout

A run gets the athlete's default pair when it arrives, and nothing recorded
whether anyone had looked at that choice since. This flag is set once the
pair is picked, changed or taken off by hand (in the app or by the coach), so
a run still carrying an unchecked automatic pair can be told apart and asked
about.

Existing rows are false: how their pair got there was never recorded.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-11-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workout",
        sa.Column("shoe_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("workout", "shoe_confirmed")
