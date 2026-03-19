"""add workout_action table

Revision ID: 5c31eec7a311
Revises: 991b5dce96e9
Create Date: 2026-03-18 16:45:30.098961

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5c31eec7a311"
down_revision: Union[str, None] = "991b5dce96e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workout_action",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workout_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("composition", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("action IN ('edit', 'delete')", name="ck_workout_action_action"),
    )
    op.create_index("ix_workout_action_created_at", "workout_action", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_workout_action_created_at", table_name="workout_action")
    op.drop_table("workout_action")
