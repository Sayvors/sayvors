"""Edited-review follow-up autopost opt-in.

Revision ID: b5a4c3d2e1f0
Revises: f1a2b3c4d5e6
Create Date: 2026-10-05

auto_reply_configs.edited_review_autopost: when a reviewer edits a review
we already answered, the follow-up reply waits for approval by default.
True = the follow-up may auto-post, through the same gates as a fresh
reply (approval_mode "auto" + rating at/above min_rating_auto).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b5a4c3d2e1f0"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auto_reply_configs",
        sa.Column(
            "edited_review_autopost",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("auto_reply_configs", "edited_review_autopost")
