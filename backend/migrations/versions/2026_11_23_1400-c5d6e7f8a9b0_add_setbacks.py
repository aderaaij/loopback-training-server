"""add setbacks (illness and injury) and their daily check-ins

A setback is an illness or injury with a start day and, once over, an end
day. Until now the coach only heard about one through the reason on a missed
run. `setback_checkin` holds how the athlete felt on a given day of it.

Also lets a missed-run check-in give "sick" or "injured" as its reason: the
reason column carries a check constraint listing the allowed values.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-11-23 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: Union[str, None] = 'b4c5d6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_REASONS = "reason IN ('busy', 'tired', 'weather', 'soreness', 'motivation', 'other')"
_NEW_REASONS = "reason IN ('busy', 'tired', 'weather', 'soreness', 'sick', 'injured', 'motivation', 'other')"


def upgrade() -> None:
    op.drop_constraint("ck_workout_feedback_reason", "workout_feedback", type_="check")
    op.create_check_constraint("ck_workout_feedback_reason", "workout_feedback", _NEW_REASONS)

    op.create_table(
        "setback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="moderate"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("body_part", sa.String(length=80), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_setback_user_id", "setback", ["user_id"])
    op.create_index("ix_setback_user_start", "setback", ["user_id", "start_date"])

    op.create_table(
        "setback_checkin",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("setback_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("setback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("setback_id", "date", name="uq_setback_checkin_day"),
    )
    op.create_index("ix_setback_checkin_setback_id", "setback_checkin", ["setback_id"])


def downgrade() -> None:
    # The old constraint has no word for these; "other" with the reason in the
    # note is what an app sends a server that predates them.
    op.execute(
        "UPDATE workout_feedback SET reason_note = CASE reason WHEN 'sick' THEN 'Sick' ELSE 'Injured' END "
        "|| COALESCE(': ' || NULLIF(reason_note, ''), ''), reason = 'other' "
        "WHERE reason IN ('sick', 'injured')"
    )
    op.drop_constraint("ck_workout_feedback_reason", "workout_feedback", type_="check")
    op.create_check_constraint("ck_workout_feedback_reason", "workout_feedback", _OLD_REASONS)

    op.drop_index("ix_setback_checkin_setback_id", table_name="setback_checkin")
    op.drop_table("setback_checkin")
    op.drop_index("ix_setback_user_start", table_name="setback")
    op.drop_index("ix_setback_user_id", table_name="setback")
    op.drop_table("setback")
