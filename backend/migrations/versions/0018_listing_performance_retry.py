"""listing performance retry

A failed performance window caused by missing market data is retried with backoff:
`attempts` counts failures and `retry_after` says when the next try is due. Windows that
already failed start at 0 attempts, so startup treats them as retryable.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-25 00:51:39.264168
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("listing_performance", schema=None) as batch_op:
        batch_op.add_column(sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("retry_after", app.db.UTCDateTime(), nullable=True))
    with op.batch_alter_table("listing_performance", schema=None) as batch_op:
        batch_op.alter_column("attempts", existing_type=sa.Integer(), server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("listing_performance", schema=None) as batch_op:
        batch_op.drop_column("retry_after")
        batch_op.drop_column("attempts")
