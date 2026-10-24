"""sim sessions

A past stretch of days played back through the engine on an account of its own.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-24 11:21:46.907046
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("sim_sessions",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("owner_user_id", sa.Integer(), nullable=True),
    sa.Column("account_id", sa.Integer(), nullable=False),
    sa.Column("symbols", sa.JSON(), nullable=False),
    sa.Column("interval", sa.String(), nullable=False),
    sa.Column("start_date", sa.Date(), nullable=False),
    sa.Column("end_date", sa.Date(), nullable=False),
    sa.Column("speed", sa.Integer(), nullable=False),
    sa.Column("cursor", app.db.UTCDateTime(), nullable=False),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_sim_sessions_account_id_accounts"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_sim_sessions"))
    )


def downgrade() -> None:
    op.drop_table("sim_sessions")
