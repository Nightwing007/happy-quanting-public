"""trading costs

Adds the broker chosen for each segment to the account, and the charges paid to each order.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 01:57:29.062869
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOT NULL columns need a default while existing rows get filled; the defaults are dropped
    # again below so the schema matches the models (which default in Python).
    # Orders placed before this step really did cost nothing, so '[]' and '0' are true values.
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("broker_india", sa.String(), nullable=False, server_default="groww"))
        batch_op.add_column(
            sa.Column("broker_international", sa.String(), nullable=False, server_default="ibkr")
        )
        batch_op.add_column(sa.Column("broker_crypto", sa.String(), nullable=False, server_default="coindcx"))

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(sa.Column("charges", sa.JSON(), nullable=False, server_default="[]"))
        batch_op.add_column(
            sa.Column("charges_total", app.db.DecimalString(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.alter_column("broker_india", existing_type=sa.String(), server_default=None)
        batch_op.alter_column("broker_international", existing_type=sa.String(), server_default=None)
        batch_op.alter_column("broker_crypto", existing_type=sa.String(), server_default=None)

    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.alter_column("charges", existing_type=sa.JSON(), server_default=None)
        batch_op.alter_column("charges_total", existing_type=app.db.DecimalString(), server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_column("charges_total")
        batch_op.drop_column("charges")

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_column("broker_crypto")
        batch_op.drop_column("broker_international")
        batch_op.drop_column("broker_india")
