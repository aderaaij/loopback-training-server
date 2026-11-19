"""add plan_link_manual to workout

A workout's plan_workout_id used to come only from the app's automatic match,
written on every upload. The athlete can now link a workout to a planned
session by hand, or unlink one, and this flag marks a link as theirs so a
later upload of the same workout does not overwrite it.

Existing rows are all automatic matches, hence false.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workout",
        sa.Column("plan_link_manual", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("workout", "plan_link_manual")
