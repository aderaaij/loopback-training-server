"""add fuel products and fuel entries

Fuelling on a workout: what the athlete drinks and eats on a run, and what
they plan to. `fuel_product` is something saved once (a gel, a drink mix).
`fuel_entry` is one thing taken or planned; it belongs either to a recorded
workout (taken) or to a queue item (planned), never both, and keeps a copy of
its product's name and figures so that editing or deleting a product leaves
the record as it was.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-11-25 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fuel_product",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("volume_ml", sa.Float(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("caffeine_mg", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_fuel_product_user_id", "fuel_product", ["user_id"])

    op.create_table(
        "fuel_entry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workout_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workout.id", ondelete="CASCADE"), nullable=True),
        sa.Column("queue_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workout_queue.id", ondelete="CASCADE"), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("fuel_product.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("volume_ml", sa.Float(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("caffeine_mg", sa.Float(), nullable=True),
        sa.Column("at_distance", sa.Float(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("(workout_id IS NULL) <> (queue_item_id IS NULL)", name="ck_fuel_entry_one_owner"),
    )
    op.create_index("ix_fuel_entry_user_id", "fuel_entry", ["user_id"])
    op.create_index("ix_fuel_entry_workout_id", "fuel_entry", ["workout_id"])
    op.create_index("ix_fuel_entry_queue_item_id", "fuel_entry", ["queue_item_id"])


def downgrade() -> None:
    op.drop_index("ix_fuel_entry_queue_item_id", table_name="fuel_entry")
    op.drop_index("ix_fuel_entry_workout_id", table_name="fuel_entry")
    op.drop_index("ix_fuel_entry_user_id", table_name="fuel_entry")
    op.drop_table("fuel_entry")
    op.drop_index("ix_fuel_product_user_id", table_name="fuel_product")
    op.drop_table("fuel_product")
