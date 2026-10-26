"""studio: staff, login, title documents, scenes, builds

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now(name: str) -> sa.Column[datetime]:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _user(name: str, *, nullable: bool = False) -> sa.Column[int]:
    return sa.Column(name, sa.BigInteger(), sa.ForeignKey("users.id"), nullable=nullable)


def _title() -> sa.Column[int]:
    return sa.Column("title_id", sa.BigInteger(), sa.ForeignKey("titles.id"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "title_documents",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _title(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        _user("updated_by", nullable=True),
        _now("updated_at"),
        sa.UniqueConstraint(
            "title_id", "kind", "key", name="title_documents_title_id_kind_key_key"
        ),
    )
    op.create_table(
        "scenes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _title(),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        _user("updated_by", nullable=True),
        _now("updated_at"),
        sa.UniqueConstraint("title_id", "key", name="scenes_title_id_key_key"),
    )
    op.create_table(
        "builds",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _title(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("hash", sa.Text(), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("warnings", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        _user("created_by", nullable=True),
        _now("created_at"),
        sa.UniqueConstraint("title_id", "version", name="builds_title_id_version_key"),
    )
    op.add_column("titles", sa.Column("status", sa.Text(), server_default="draft", nullable=False))
    op.add_column("titles", sa.Column("active_build_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "titles_active_build_id_fkey", "titles", "builds", ["active_build_id"], ["id"]
    )
    op.create_table(
        "staff",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("role", sa.Text(), nullable=False),
        _now("created_at"),
    )
    op.create_table(
        "login_tokens",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        _user("user_id"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "studio_sessions",
        sa.Column("token_hash", sa.Text(), primary_key=True),
        _user("user_id"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _now("created_at"),
    )


def downgrade() -> None:
    op.drop_table("studio_sessions")
    op.drop_table("login_tokens")
    op.drop_table("staff")
    op.drop_constraint("titles_active_build_id_fkey", "titles", type_="foreignkey")
    op.drop_column("titles", "active_build_id")
    op.drop_column("titles", "status")
    op.drop_table("builds")
    op.drop_table("scenes")
    op.drop_table("title_documents")
