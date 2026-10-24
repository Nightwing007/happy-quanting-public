"""sim_strategy

A virtual sim session can run a strategy (library, saved, uploaded source or a marketplace
listing's pinned version). Existing sessions have none.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-24 19:57:12.467552
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sim_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("strategy_kind", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("strategy_key", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("user_algo_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("listing_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("listing_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("params", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            "fk_sim_sessions_user_algo_id", "user_algos", ["user_algo_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_foreign_key(
            "fk_sim_sessions_listing_id", "algo_listings", ["listing_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("sim_sessions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_sim_sessions_listing_id", type_="foreignkey")
        batch_op.drop_constraint("fk_sim_sessions_user_algo_id", type_="foreignkey")
        batch_op.drop_column("params")
        batch_op.drop_column("source")
        batch_op.drop_column("listing_version")
        batch_op.drop_column("listing_id")
        batch_op.drop_column("user_algo_id")
        batch_op.drop_column("strategy_key")
        batch_op.drop_column("strategy_kind")
