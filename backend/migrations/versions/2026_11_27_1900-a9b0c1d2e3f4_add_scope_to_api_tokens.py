"""add scope to api_tokens (tokens that can only do what the coach does)

A token was always the athlete, for the whole API. The ones an assistant
holds get a narrower kind, `coach`, which is refused everywhere but on the
routes the coach's tools call (app/token_scope.py). Every existing token
stays `full`: nothing that works today stops working.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-11-27 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'f8a9b0c1d2e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_tokens",
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="full"),
    )
    op.create_check_constraint("ck_api_tokens_scope", "api_tokens", "scope IN ('full', 'coach')")


def downgrade() -> None:
    # Without the column every token is the athlete again. One that was handed
    # out as a coach token must not come out of a downgrade as more than that,
    # so those are revoked; the assistants holding them sign in again.
    op.execute("DELETE FROM api_tokens WHERE scope = 'coach'")
    op.drop_constraint("ck_api_tokens_scope", "api_tokens", type_="check")
    op.drop_column("api_tokens", "scope")
