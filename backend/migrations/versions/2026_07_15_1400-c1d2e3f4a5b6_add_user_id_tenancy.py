"""add user_id to all data tables (multi-user tenancy)

Adds a NOT NULL ``user_id`` FK to every data table and backfills existing rows
to the seeded 'admin' account (all pre-existing data belonged to the single
original user). Also swaps the two globally-unique constraints for per-user
composites so two users can each have a health-metrics row for the same date
and feedback for the same workout_id.

Revision ID: c1d2e3f4a5b6
Revises: b1t2o3k4e5n6
Create Date: 2026-07-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b1t2o3k4e5n6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# All data tables that gain a user_id. (users / api_tokens already have identity.)
_TABLES = [
    "workout",
    "workout_queue",
    "workout_action",
    "workout_feedback",
    "workout_inventory",
    "daily_health_metrics",
    "plans",
    "plan_note",
]


def upgrade() -> None:
    conn = op.get_bind()
    admin_id = conn.execute(sa.text("SELECT id FROM users WHERE username = 'admin'")).scalar()
    if admin_id is None:
        raise RuntimeError("No 'admin' user found; migration b1t2o3k4e5n6 must run first.")

    for table in _TABLES:
        op.add_column(table, sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
        conn.execute(
            sa.text(f"UPDATE {table} SET user_id = :admin_id WHERE user_id IS NULL"),
            {"admin_id": admin_id},
        )
        op.alter_column(table, "user_id", nullable=False)
        op.create_foreign_key(
            f"fk_{table}_user_id", table, "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        op.create_index(f"ix_{table}_user_id", table, ["user_id"])

    # Global-uniqueness → per-user composites.
    op.drop_constraint("uq_daily_health_metrics_date", "daily_health_metrics", type_="unique")
    op.create_unique_constraint(
        "uq_daily_health_metrics_user_date", "daily_health_metrics", ["user_id", "date"]
    )
    op.drop_constraint("uq_workout_feedback_workout_id", "workout_feedback", type_="unique")
    op.create_unique_constraint(
        "uq_workout_feedback_user_workout", "workout_feedback", ["user_id", "workout_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_workout_feedback_user_workout", "workout_feedback", type_="unique")
    op.create_unique_constraint(
        "uq_workout_feedback_workout_id", "workout_feedback", ["workout_id"]
    )
    op.drop_constraint("uq_daily_health_metrics_user_date", "daily_health_metrics", type_="unique")
    op.create_unique_constraint("uq_daily_health_metrics_date", "daily_health_metrics", ["date"])

    for table in _TABLES:
        op.drop_index(f"ix_{table}_user_id", table_name=table)
        op.drop_constraint(f"fk_{table}_user_id", table, type_="foreignkey")
        op.drop_column(table, "user_id")
