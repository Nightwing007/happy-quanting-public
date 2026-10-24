"""bar cache

Historical bars fetched from the provider, and the day spans already asked for, so a past range
is fetched once.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-24 11:15:52.046055
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("bar_cache",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("symbol", sa.String(), nullable=False),
    sa.Column("interval", sa.String(), nullable=False),
    sa.Column("ts", sa.BigInteger(), nullable=False),
    sa.Column("open", app.db.DecimalString(), nullable=False),
    sa.Column("high", app.db.DecimalString(), nullable=False),
    sa.Column("low", app.db.DecimalString(), nullable=False),
    sa.Column("close", app.db.DecimalString(), nullable=False),
    sa.Column("volume", sa.BigInteger(), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_bar_cache")),
    sa.UniqueConstraint("symbol", "interval", "ts", name="uq_bar_cache_symbol_interval_ts")
    )
    op.create_table("history_spans",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("symbol", sa.String(), nullable=False),
    sa.Column("interval", sa.String(), nullable=False),
    sa.Column("start_date", sa.Date(), nullable=False),
    sa.Column("end_date", sa.Date(), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_history_spans")),
    sa.UniqueConstraint(
        "symbol", "interval", "start_date", name="uq_history_spans_symbol_interval_start_date"
    )
    )


def downgrade() -> None:
    op.drop_table("history_spans")
    op.drop_table("bar_cache")
