"""account kind and owner

Accounts gain a `kind` (live, sim, backtest or algo) and a nullable `user_id`. Every existing
account is the person's live account. `user_id` has no foreign key yet: users come later.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-24 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("kind", sa.String(), nullable=False, server_default="live"))
        batch_op.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
    # The default only back-fills existing rows; new rows get theirs from the model.
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.alter_column("kind", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_column("user_id")
        batch_op.drop_column("kind")
