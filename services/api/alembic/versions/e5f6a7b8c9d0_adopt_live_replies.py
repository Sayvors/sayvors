"""Adopt live Google replies into review_replies.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-26

Localith returns the business's live reply on every review payload. The
adapter used to collapse that to a boolean, so a review answered on the
listing had no stored response and the detail page could only offer a
blind "reply again". These columns let the sync adopt what Google already
shows:

  reply_external_id — the provider's reply id, so a later poll can tell
                      "unchanged" from "the business edited it in GBP".
  replied_at        — when the provider published that reply (distinct
                      from created_at, which is when we first saw it).

Both nullable: existing rows stay NULL and behave exactly as before.
"""
import sqlalchemy as sa

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_replies",
        sa.Column("reply_external_id", sa.String(64), nullable=True),
    )
    op.add_column(
        "review_replies",
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_review_replies_reply_external_id",
        "review_replies",
        ["reply_external_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_review_replies_reply_external_id", table_name="review_replies")
    op.drop_column("review_replies", "replied_at")
    op.drop_column("review_replies", "reply_external_id")
