"""users

Users and login sessions. Rows that had no owner go to a `demo` user whose password is unusable
until the app sets one at startup.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-24 14:07:26.123765
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("users",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("username", sa.String(length=30), nullable=False),
    sa.Column("display_name", sa.String(), nullable=False),
    sa.Column("avatar_url", sa.String(), nullable=True),
    sa.Column("bio", sa.Text(), nullable=False),
    sa.Column("password_hash", sa.String(), nullable=False),
    sa.Column("is_creator", sa.Boolean(), nullable=False),
    sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    sa.UniqueConstraint("username", name=op.f("uq_users_username"))
    )
    op.create_table("user_sessions",
    sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("token_hash", sa.String(length=64), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=False),
    sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
    sa.Column("expires_at", app.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_sessions_user_id"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
    sa.UniqueConstraint("token_hash", name=op.f("uq_user_sessions_token_hash"))
    )

    bind = op.get_bind()
    users = sa.table(
        "users",
        sa.column("username", sa.String),
        sa.column("display_name", sa.String),
        sa.column("bio", sa.Text),
        sa.column("password_hash", sa.String),
        sa.column("is_creator", sa.Boolean),
        sa.column("created_at", app.db.UTCDateTime()),
    )
    bind.execute(
        sa.insert(users).values(
            username="demo",
            display_name="Demo",
            bio="",
            password_hash="!",  # unusable until ensure_demo_password sets one
            is_creator=False,
            created_at=datetime.now(UTC),
        )
    )
    demo_id = bind.execute(sa.text("SELECT id FROM users WHERE username = 'demo'")).scalar_one()
    for table, column in (
        ("accounts", "user_id"),
        ("sim_sessions", "owner_user_id"),
        ("backtests", "owner_user_id"),
        ("user_algos", "owner_user_id"),
    ):
        bind.execute(
            sa.text(f"UPDATE {table} SET {column} = :uid WHERE {column} IS NULL"), {"uid": demo_id}
        )


def downgrade() -> None:
    op.drop_table("user_sessions")
    op.drop_table("users")
