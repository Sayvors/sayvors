"""Append-only, plain-language progress feed for first-connect imports.

The modal needs a reassuring chronological story, not just a percentage:
reviews found per location, replies ready, posting results and failures. The
feed is persisted so closing/reopening the modal (or a worker resume) keeps the
same sequence.

Revision ID: f4b7c2a9d1e8
Revises: d7e8f9a0b1c2
Create Date: 2026-11-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4b7c2a9d1e8"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connect_import_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["session_id"], ["connect_import_sessions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connect_import_events_session_id", "connect_import_events", ["session_id"]
    )
    op.create_index(
        "ix_connect_import_events_session_created",
        "connect_import_events",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("connect_import_events")
