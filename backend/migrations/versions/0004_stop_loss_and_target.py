"""stop loss and target

Trades gain an optional stop-loss price, target price and the moment they lapse. All nullable:
no existing trade has any, and nothing existing changes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24 09:19:45.208559
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.add_column(sa.Column("stop_price", app.db.DecimalString(), nullable=True))
        batch_op.add_column(sa.Column("target_price", app.db.DecimalString(), nullable=True))
        batch_op.add_column(sa.Column("protection_expires_at", app.db.UTCDateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_column("protection_expires_at")
        batch_op.drop_column("target_price")
        batch_op.drop_column("stop_price")
