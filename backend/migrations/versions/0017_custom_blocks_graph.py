"""custom_blocks_graph

The block editor: a table of each person's custom blocks, and the block graph a saved algorithm's
`source` was compiled from (NULL for code and library algorithms).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-24 21:40:49.415277
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import app.db

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_blocks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("created_at", app.db.UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], name="fk_custom_blocks_owner_user_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_blocks")),
    )
    with op.batch_alter_table("user_algos", schema=None) as batch_op:
        batch_op.add_column(sa.Column("graph", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_algos", schema=None) as batch_op:
        batch_op.drop_column("graph")

    op.drop_table("custom_blocks")
