"""user_algos

Saved algorithms: a predefined strategy plus the settings someone tuned.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24 13:44:10.146886
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("user_algos",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("owner_user_id", sa.Integer(), nullable=True),
    sa.Column("name", sa.String(), nullable=False),
    sa.Column("description", sa.String(), nullable=False),
    sa.Column("strategy_key", sa.String(), nullable=False),
    sa.Column("params", sa.JSON(), nullable=False),
    sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_user_algos"))
    )


def downgrade() -> None:
    op.drop_table("user_algos")
