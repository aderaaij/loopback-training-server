"""add daily_nutrition table

Daily dietary totals from HealthKit (energy + macros + the micronutrients a
food-logging app happens to write). Separate from daily_health_metrics because
the provenance differs (food loggers, not the watch) and coverage is sparse —
see app/models/nutrition.py.

Revision ID: c3n4u5t6r7i8
Revises: f4a5b6c7d8e9
Create Date: 2026-07-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3n4u5t6r7i8'
down_revision: Union[str, None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'daily_nutrition',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('energy_kcal', sa.Float(), nullable=True),
        sa.Column('carbs_g', sa.Float(), nullable=True),
        sa.Column('protein_g', sa.Float(), nullable=True),
        sa.Column('fat_g', sa.Float(), nullable=True),
        sa.Column('saturated_fat_g', sa.Float(), nullable=True),
        sa.Column('fiber_g', sa.Float(), nullable=True),
        sa.Column('sugar_g', sa.Float(), nullable=True),
        sa.Column('sodium_mg', sa.Float(), nullable=True),
        sa.Column('potassium_mg', sa.Float(), nullable=True),
        sa.Column('cholesterol_mg', sa.Float(), nullable=True),
        sa.Column('water_ml', sa.Float(), nullable=True),
        sa.Column('caffeine_mg', sa.Float(), nullable=True),
        sa.Column('micros', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('entry_count', sa.Integer(), nullable=True),
        sa.Column('sources', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('partial', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'date', name='uq_daily_nutrition_user_date'),
    )
    op.create_index('ix_daily_nutrition_user_id', 'daily_nutrition', ['user_id'])
    op.create_index('ix_daily_nutrition_user_date', 'daily_nutrition', ['user_id', 'date'])


def downgrade() -> None:
    op.drop_index('ix_daily_nutrition_user_date', table_name='daily_nutrition')
    op.drop_index('ix_daily_nutrition_user_id', table_name='daily_nutrition')
    op.drop_table('daily_nutrition')
