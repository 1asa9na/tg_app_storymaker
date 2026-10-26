"""titles, saves, action_log, account_progress, user_achievements

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_at(name: str = "created_at") -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "titles",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort", sa.Integer(), server_default="0", nullable=False),
        _created_at(),
        sa.UniqueConstraint("slug", name="titles_slug_key"),
    )
    op.create_table(
        "saves",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title_id", sa.BigInteger(), sa.ForeignKey("titles.id"), nullable=False),
        sa.Column("slot", sa.Text(), server_default="main", nullable=False),
        sa.Column("build", sa.Text(), nullable=False),
        sa.Column("state", postgresql.JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        _created_at(),
        _created_at("updated_at"),
        sa.PrimaryKeyConstraint("user_id", "title_id", "slot", name="saves_pkey"),
    )
    op.create_table(
        "action_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title_id", sa.BigInteger(), sa.ForeignKey("titles.id"), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("action", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        _created_at(),
        sa.UniqueConstraint(
            "user_id",
            "title_id",
            "slot",
            "request_id",
            name="action_log_user_id_title_id_slot_request_id_key",
        ),
    )
    op.create_table(
        "account_progress",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("xp", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("level", sa.Integer(), server_default="1", nullable=False),
        _created_at("updated_at"),
    )
    op.create_table(
        "user_achievements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title_id", sa.BigInteger(), sa.ForeignKey("titles.id"), nullable=True),
        sa.Column("achievement_key", sa.Text(), nullable=False),
        _created_at("unlocked_at"),
        sa.UniqueConstraint(
            "user_id",
            "title_id",
            "achievement_key",
            name="user_achievements_user_id_title_id_achievement_key_key",
            postgresql_nulls_not_distinct=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("user_achievements")
    op.drop_table("account_progress")
    op.drop_table("action_log")
    op.drop_table("saves")
    op.drop_table("titles")
