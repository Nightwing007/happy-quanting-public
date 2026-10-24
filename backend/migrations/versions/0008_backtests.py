"""backtests

A strategy run over a past date range: its settings, progress and stored results.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-24 11:58:00.530396
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("backtests",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("owner_user_id", sa.Integer(), nullable=True),
    sa.Column("strategy_key", sa.String(), nullable=False),
    sa.Column("params", sa.JSON(), nullable=False),
    sa.Column("symbols", sa.JSON(), nullable=False),
    sa.Column("interval", sa.String(), nullable=False),
    sa.Column("start_date", sa.Date(), nullable=False),
    sa.Column("end_date", sa.Date(), nullable=False),
    sa.Column("starting_cash", app.db.DecimalString(), nullable=False),
    sa.Column("account_currency", sa.String(length=3), nullable=False),
    sa.Column("brokers", sa.JSON(), nullable=False),
    sa.Column("status", sa.String(), nullable=False),
    sa.Column("progress", sa.Integer(), nullable=False),
    sa.Column("error", sa.String(), nullable=True),
    sa.Column("results", sa.JSON(), nullable=True),
    sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_backtests"))
    )


def downgrade() -> None:
    op.drop_table("backtests")
