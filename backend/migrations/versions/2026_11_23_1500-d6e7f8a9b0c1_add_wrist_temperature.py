"""add sleeping wrist temperature to the daily health metrics

The Apple Watch's sleeping wrist temperature in °C, one reading per night,
stored on the day the athlete woke up. A sustained rise is the watch's
clearest illness signal, and the setback recovery check compares it with the
athlete's own earlier nights.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-11-23 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, None] = 'c5d6e7f8a9b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("daily_health_metrics", sa.Column("wrist_temperature", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_health_metrics", "wrist_temperature")
