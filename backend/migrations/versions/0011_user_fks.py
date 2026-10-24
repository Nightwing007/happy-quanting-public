"""user_fks

Foreign keys from the owner columns to users.id.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-24 14:12:13.246536
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.create_foreign_key("fk_accounts_user_id", "users", ["user_id"], ["id"])

    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.create_foreign_key("fk_backtests_owner_user_id", "users", ["owner_user_id"], ["id"])

    with op.batch_alter_table("sim_sessions", schema=None) as batch_op:
        batch_op.create_foreign_key("fk_sim_sessions_owner_user_id", "users", ["owner_user_id"], ["id"])

    with op.batch_alter_table("user_algos", schema=None) as batch_op:
        batch_op.create_foreign_key("fk_user_algos_owner_user_id", "users", ["owner_user_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("user_algos", schema=None) as batch_op:
        batch_op.drop_constraint("fk_user_algos_owner_user_id", type_="foreignkey")

    with op.batch_alter_table("sim_sessions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_sim_sessions_owner_user_id", type_="foreignkey")

    with op.batch_alter_table("backtests", schema=None) as batch_op:
        batch_op.drop_constraint("fk_backtests_owner_user_id", type_="foreignkey")

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_constraint("fk_accounts_user_id", type_="foreignkey")
