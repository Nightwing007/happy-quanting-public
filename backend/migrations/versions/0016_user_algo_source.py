"""user_algo_source

A saved algorithm can hold code written in the editor (`source`); library-based ones keep it NULL.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-24 20:08:32.303784
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("user_algos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_algos", schema=None) as batch_op:
        batch_op.drop_column("source")
