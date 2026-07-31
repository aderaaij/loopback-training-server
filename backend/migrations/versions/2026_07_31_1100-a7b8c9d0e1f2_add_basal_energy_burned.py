"""add basal_energy_burned to daily_health_metrics

The table already holds active energy (movement + exercise), which is the
"leeway earned" figure a food-logging app shows. Total daily expenditure needs
the resting half too: TDEE = basal + active. HealthKit estimates basal
continuously, so this is a stored measurement rather than a BMR formula over
the athlete's profile.

Nullable with no backfill: no historical source exists server-side, and the
column stays null until the iOS app ships the sync (docs/app-basal-energy-handoff.md).
Every consumer degrades to active-only meanwhile.

Revision ID: a7b8c9d0e1f2
Revises: c3n4u5t6r7i8
Create Date: 2026-07-31 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'c3n4u5t6r7i8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'daily_health_metrics',
        sa.Column('basal_energy_burned', sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('daily_health_metrics', 'basal_energy_burned')
