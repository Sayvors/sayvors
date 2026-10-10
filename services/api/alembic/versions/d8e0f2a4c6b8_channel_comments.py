"""Comments inbox: store comments on the tenant's own media.

Revision ID: d8e0f2a4c6b8
Revises: c7d9e1f3a5b7
Create Date: 2026-10-10

comment.received webhooks were parsed and ledgered but had nowhere to land.
channel_comments gives them a home — replay dedupe on the platform comment
id, reply threading via parent id, and a lifecycle (hidden / deleted_at /
platform_timestamp) so the tenant's comment section is answerable from
Sayvors with full history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e0f2a4c6b8"
down_revision: Union[str, None] = "c7d9e1f3a5b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("platform_comment_id", sa.String(200), nullable=True),
        sa.Column("parent_platform_comment_id", sa.String(200), nullable=True),
        sa.Column("media_id", sa.String(200), nullable=True),
        sa.Column(
            "direction",
            sa.Enum("inbound", "outbound", name="comment_direction"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author_id", sa.String(64), nullable=True),
        sa.Column("author_name", sa.String(120), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "status",
            sa.Enum("received", "sent", "failed", name="comment_status"),
            nullable=False,
            server_default="received",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("platform_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Index("ix_channel_comments_channel_id", "channel_id"),
        sa.Index("ix_channel_comments_platform_id", "platform_comment_id"),
        sa.Index("ix_channel_comments_parent", "parent_platform_comment_id"),
        sa.Index("ix_channel_comments_media", "channel_id", "media_id", "created_at"),
    )


def downgrade() -> None:
    op.drop_table("channel_comments")
    sa.Enum(name="comment_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="comment_direction").drop(op.get_bind(), checkfirst=True)
