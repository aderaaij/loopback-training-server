"""add shoes and the pair worn on each workout

Shoe tracking: a pair has a name, the distance already on it when it was
added, an optional target, and at most one pair per user is the default that
new runs are assigned to. A pair's mileage is not stored; it is the starting
distance plus the workouts that reference it.

Existing workouts keep shoe_id NULL. Distance from before a pair was added is
what its starting distance is for.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-17 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shoe",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("start_distance", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_distance", sa.Float(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_shoe_user_id", "shoe", ["user_id"])
    op.create_index(
        "uq_shoe_one_default_per_user", "shoe", ["user_id"], unique=True, postgresql_where=sa.text("is_default")
    )

    op.add_column("workout", sa.Column("shoe_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_workout_shoe_id", "workout", "shoe", ["shoe_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_workout_shoe_id", "workout", ["shoe_id"])


def downgrade() -> None:
    op.drop_index("ix_workout_shoe_id", table_name="workout")
    op.drop_constraint("fk_workout_shoe_id", "workout", type_="foreignkey")
    op.drop_column("workout", "shoe_id")
    op.drop_index("uq_shoe_one_default_per_user", table_name="shoe")
    op.drop_index("ix_shoe_user_id", table_name="shoe")
    op.drop_table("shoe")
