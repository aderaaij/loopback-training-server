"""add sleep_samples table

Raw HealthKit sleep samples shipped by the app. The daily sleep rollup in
daily_health_metrics becomes a server-derived view over these rows
(app/sleep_merge.py + app/sleep_service.py) instead of a client-authored
aggregate — the client-side windowed aggregation is what corrupted July 2026
(see docs/sleep-data-handoff.md).

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-07-23 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sleep_samples',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('stage', sa.String(length=20), nullable=False),
        sa.Column('source', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'start_at', 'end_at', 'stage', 'source', name='uq_sleep_samples_identity'),
        sa.CheckConstraint('end_at > start_at', name='sleep_sample_span_positive'),
        sa.CheckConstraint(
            "stage IN ('rem', 'core', 'deep', 'awake', 'unspecified', 'in_bed')",
            name='sleep_sample_stage_valid',
        ),
    )
    op.create_index('ix_sleep_samples_user_id', 'sleep_samples', ['user_id'])
    op.create_index('ix_sleep_samples_user_span', 'sleep_samples', ['user_id', 'end_at', 'start_at'])


def downgrade() -> None:
    op.drop_index('ix_sleep_samples_user_span', table_name='sleep_samples')
    op.drop_index('ix_sleep_samples_user_id', table_name='sleep_samples')
    op.drop_table('sleep_samples')
