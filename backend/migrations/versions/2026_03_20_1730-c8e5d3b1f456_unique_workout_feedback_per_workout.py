"""unique workout_feedback per workout

Revision ID: c8e5d3b1f456
Revises: b7d4f2a9e123
Create Date: 2026-03-20 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e5d3b1f456"
down_revision: Union[str, None] = "b7d4f2a9e123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_workout_feedback_workout_id", "workout_feedback", ["workout_id"])


def downgrade() -> None:
    op.drop_constraint("uq_workout_feedback_workout_id", "workout_feedback")
