"""listing_versions

Each version's code kept server-side, so subscribers stay on the version they chose; and the code
of a backtest of uploaded source.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-24 19:39:03.679694
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "listing_versions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("strategy_key", sa.String(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("interval", sa.String(), nullable=False),
        sa.Column("changelog", sa.String(length=500), nullable=True),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["algo_listings.id"], name="fk_listing_versions_listing_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listing_versions")),
        sa.UniqueConstraint("listing_id", "version", name="uq_listing_versions"),
    )
    # One row per existing listing, from its current fields. Earlier versions were never kept and
    # subscribers used to follow the current one, so they are all pinned to it here.
    op.execute(
        "INSERT INTO listing_versions "
        "(listing_id, version, source, strategy_key, params, interval, created_at) "
        "SELECT id, version, source, strategy_key, params, interval, updated_at FROM algo_listings"
    )
    op.execute(
        "UPDATE subscriptions SET listing_version = "
        "(SELECT version FROM algo_listings WHERE algo_listings.id = subscriptions.listing_id)"
    )
    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.drop_column("source")

    op.drop_table("listing_versions")
