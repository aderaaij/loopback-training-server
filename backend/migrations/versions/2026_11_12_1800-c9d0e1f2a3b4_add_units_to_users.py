"""add display-units preference to users

Metric / imperial used to live in the dashboard's localStorage, so the phone
and the coach could not see it: the app kept its own copy and the coach kept
authoring in kilometers for a runner who reads miles. Storing it on the user
gives all three one answer.

NULL means "never chosen", and existing rows stay NULL. That is not the same
as metric: the phone defaults from the device's region, and it can only do
that if it can tell an unset preference from a metric one.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-12 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("units", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("units_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "units_updated_at")
    op.drop_column("users", "units")
