"""add per-domain data consent to users

The athlete chooses in the iOS app which categories of health data the coach
may read (training / recovery / body / activity / nutrition) and the app
reports the whole set on every launch. Stored here as a text[] so adding a
domain needs no migration and an unknown one round-trips harmlessly.

The default is deliberately permissive — all five. An absent record means "not
yet reported", not "restricted": an install predating consent had no way to
limit anything, and reading that silence as a restriction would strip a working
coach of its context. A current app whose push failed re-pushes on the next
launch, so the permissive window is short and self-healing. This mirrors the
iOS migration, which moved an existing health-syncing install to all five
domains rather than revoking consent on the athlete's behalf.

Both timestamps stay NULL here, including for existing rows: nobody has
reported yet, and that is exactly the state worth being able to see.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-31 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "data_consent",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['training','recovery','body','activity','nutrition']::text[]"),
        ),
    )
    op.add_column(
        "users", sa.Column("data_consent_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users", sa.Column("data_consent_reported_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "data_consent_reported_at")
    op.drop_column("users", "data_consent_updated_at")
    op.drop_column("users", "data_consent")
