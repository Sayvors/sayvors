"""Durable first-connect Google import sessions.

The modal needs a server-side lifecycle: fetch every review, wait for the
merchant's scope choice, generate drafts, then publish selected drafts. Two
tables hold that state so closing the modal or reloading the page resumes
exactly where the worker left off.

Revision ID: d7e8f9a0b1c2
Revises: c8f5a2b3d6e7
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c8f5a2b3d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connect_import_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="queued"),
        sa.Column("scope_days", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("total_locations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_locations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_reviews", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_reviews", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_drafts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("drafts_ready", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("drafts_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_connect_import_sessions_user_id", "connect_import_sessions", ["user_id"])
    op.create_index("ix_connect_import_sessions_status", "connect_import_sessions", ["status"])

    op.create_table(
        "connect_import_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("review_id", sa.String(length=500), nullable=False),
        sa.Column("location_name", sa.String(length=255), nullable=True),
        sa.Column("reviewer_name", sa.String(length=255), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("review_text", sa.Text(), nullable=True),
        sa.Column("review_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("reply_id", sa.String(length=36), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["connect_import_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reply_id"], ["review_replies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "channel_id", "review_id",
            name="uq_connect_import_session_review",
        ),
    )
    op.create_index("ix_connect_import_items_session_id", "connect_import_items", ["session_id"])
    op.create_index("ix_connect_import_items_channel_id", "connect_import_items", ["channel_id"])
    op.create_index("ix_connect_import_items_review_id", "connect_import_items", ["review_id"])
    op.create_index("ix_connect_import_items_status", "connect_import_items", ["status"])
    op.create_index("ix_connect_import_items_reply_id", "connect_import_items", ["reply_id"])
    op.create_index(
        "ix_connect_import_items_session_status",
        "connect_import_items", ["session_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("connect_import_items")
    op.drop_table("connect_import_sessions")
