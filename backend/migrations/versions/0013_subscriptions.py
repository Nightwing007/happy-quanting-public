"""subscriptions

Subscriptions to listings, the profit-share ledger and capital transfers.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-24 15:21:19.577812
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscriber_user_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("listing_version", sa.Integer(), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("capital", app.db.DecimalString(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("fee_percent", app.db.DecimalString(), nullable=False),
        sa.Column("high_water_mark", app.db.DecimalString(), nullable=False),
        sa.Column("fees_paid", app.db.DecimalString(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.Column("stopped_at", app.db.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_subscriptions_account_id"),
        sa.ForeignKeyConstraint(["listing_id"], ["algo_listings.id"], name="fk_subscriptions_listing_id"),
        sa.ForeignKeyConstraint(
            ["subscriber_user_id"], ["users.id"], name="fk_subscriptions_subscriber_user_id"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_table(
        "cash_transfers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("amount", app.db.DecimalString(), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], name="fk_cash_transfers_subscription_id"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cash_transfers")),
    )
    op.create_table(
        "fee_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("creator_user_id", sa.Integer(), nullable=False),
        sa.Column("subscriber_user_id", sa.Integer(), nullable=False),
        sa.Column("amount", app.db.DecimalString(), nullable=False),
        sa.Column("shortfall", app.db.DecimalString(), nullable=False),
        sa.Column("profit_before", app.db.DecimalString(), nullable=False),
        sa.Column("profit_after", app.db.DecimalString(), nullable=False),
        sa.Column("hwm_before", app.db.DecimalString(), nullable=False),
        sa.Column("hwm_after", app.db.DecimalString(), nullable=False),
        sa.Column("fee_percent", app.db.DecimalString(), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["creator_user_id"], ["users.id"], name="fk_fee_ledger_creator_user_id"),
        sa.ForeignKeyConstraint(
            ["subscriber_user_id"], ["users.id"], name="fk_fee_ledger_subscriber_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], name="fk_fee_ledger_subscription_id"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_ledger")),
    )


def downgrade() -> None:
    op.drop_table("fee_ledger")
    op.drop_table("cash_transfers")
    op.drop_table("subscriptions")
