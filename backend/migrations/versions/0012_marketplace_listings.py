"""marketplace_listings

Algorithm listings and their server-computed performance.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24 15:03:14.021299
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "algo_listings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("tagline", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("markets", sa.JSON(), nullable=False),
        sa.Column("test_symbols", sa.JSON(), nullable=False),
        sa.Column("interval", sa.String(), nullable=False),
        sa.Column("fee_percent", app.db.DecimalString(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("strategy_key", sa.String(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.Column("updated_at", app.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name="fk_algo_listings_owner_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_algo_listings")),
    )
    op.create_table(
        "listing_performance",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("window", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("start", sa.Date(), nullable=False),
        sa.Column("end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("computed_at", app.db.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["listing_id"], ["algo_listings.id"], name="fk_listing_performance_listing_id"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listing_performance")),
        sa.UniqueConstraint("listing_id", "window", "version", name="uq_listing_performance"),
    )


def downgrade() -> None:
    op.drop_table("listing_performance")
    op.drop_table("algo_listings")
