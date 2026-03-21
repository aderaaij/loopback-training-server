"""add workout_feedback table

Revision ID: b7d4f2a9e123
Revises: a3f2b8e1c456
Create Date: 2026-03-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b7d4f2a9e123"
down_revision: Union[str, None] = "a3f2b8e1c456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workout_feedback",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workout_id", sa.UUID(), nullable=False),
        sa.Column("workout_name", sa.Text(), nullable=False),
        sa.Column("scheduled_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("reason_note", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("new_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("reason IN ('busy', 'tired', 'weather', 'soreness', 'motivation', 'other')", name="ck_workout_feedback_reason"),
        sa.CheckConstraint("action IN ('move', 'adjust', 'skip')", name="ck_workout_feedback_action"),
    )
    op.create_index("idx_workout_feedback_scheduled", "workout_feedback", [sa.text("scheduled_date DESC")])
    op.create_index("idx_workout_feedback_workout", "workout_feedback", ["workout_id"])
    op.create_index("idx_workout_feedback_action", "workout_feedback", ["action"])


def downgrade() -> None:
    op.drop_index("idx_workout_feedback_action", table_name="workout_feedback")
    op.drop_index("idx_workout_feedback_workout", table_name="workout_feedback")
    op.drop_index("idx_workout_feedback_scheduled", table_name="workout_feedback")
    op.drop_table("workout_feedback")
