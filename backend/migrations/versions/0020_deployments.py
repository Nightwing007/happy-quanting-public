"""deployments

`deployments` is a user's own algorithm running live on a dedicated algo account, with a pinned
snapshot of what runs. `cash_transfers` now also records a deployment's capital moving, so its
`subscription_id` becomes nullable and `deployment_id` is added.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-25 05:00:53.166198
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("capital", app.db.DecimalString(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.Column("stopped_at", app.db.UTCDateTime(), nullable=True),
        sa.Column("strategy_kind", sa.String(), nullable=False),
        sa.Column("strategy_key", sa.String(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("user_algo_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], name="fk_deployments_account_id"),
        sa.ForeignKeyConstraint(
            ["user_algo_id"], ["user_algos.id"], name="fk_deployments_user_algo_id", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_deployments_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_deployments")),
    )
    with op.batch_alter_table("cash_transfers", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deployment_id", sa.Integer(), nullable=True))
        batch_op.alter_column("subscription_id", existing_type=sa.INTEGER(), nullable=True)
        batch_op.create_foreign_key(
            "fk_cash_transfers_deployment_id", "deployments", ["deployment_id"], ["id"]
        )


def downgrade() -> None:
    # A deployment's transfers have no subscription to point at, so they go with the table.
    op.execute("DELETE FROM cash_transfers WHERE subscription_id IS NULL")
    with op.batch_alter_table("cash_transfers", schema=None) as batch_op:
        batch_op.drop_constraint("fk_cash_transfers_deployment_id", type_="foreignkey")
        batch_op.alter_column("subscription_id", existing_type=sa.INTEGER(), nullable=False)
        batch_op.drop_column("deployment_id")
    op.drop_table("deployments")
