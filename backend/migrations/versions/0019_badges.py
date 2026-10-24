"""badges

`user_badges` holds the badges a user has earned. `trades.had_stop` is the lasting record that a
stop-loss was set (the stop itself is cleared when a trade closes), and
`users.badge_summary_seen` marks the one-time backfill notice as acknowledged.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-25 01:12:36.990677
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_badges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("badge_id", sa.String(), nullable=False),
        sa.Column("earned_at", app.db.UTCDateTime(), nullable=False),
        sa.Column("seen", sa.Boolean(), nullable=False),
        sa.Column("backfilled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_badges_user_id_users"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_badges")),
        sa.UniqueConstraint("user_id", "badge_id", name="uq_user_badges_user_id_badge_id"),
    )
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.add_column(sa.Column("had_stop", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("badge_summary_seen", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    # Backfill: a trade that still has a stop certainly had one, and one that closed by its stop or
    # its target was protected. Older trades protected only by a target, and closed by hand, left
    # no trace, so they count as unprotected: an approximation that errs towards not awarding.
    op.execute(
        "UPDATE trades SET had_stop = 1 WHERE stop_price IS NOT NULL OR closed_how IN ('stop_loss', 'target')"
    )
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.alter_column("had_stop", existing_type=sa.Boolean(), server_default=None)
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("badge_summary_seen", existing_type=sa.Boolean(), server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("badge_summary_seen")
    with op.batch_alter_table("trades", schema=None) as batch_op:
        batch_op.drop_column("had_stop")
    op.drop_table("user_badges")
