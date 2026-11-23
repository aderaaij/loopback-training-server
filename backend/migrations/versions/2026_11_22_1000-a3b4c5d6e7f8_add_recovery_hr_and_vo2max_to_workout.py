"""add heart rate recovery and VO2 max to workout

Two figures the watch produces around a workout and that until now never
reached the server tied to it:

- heart rate as the workout ended and one and two minutes later, from which
  the recovery drop follows;
- the VO2 max estimate Health recorded for the workout. The daily metrics row
  already carries a per-day average; this is the reading for one run.

All nullable. Existing rows stay null until the app sends them again.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-11-22 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("end_heart_rate", "heart_rate_after_1min", "heart_rate_after_2min", "vo2_max")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("workout", sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("workout", name)
