"""staff registry + review staff mentions (employee performance from reviews)

Revision ID: 20261112140000
Revises: 20261112130000
Create Date: 2026-11-12

§33 of the readiness report: the owner registers employees per branch, the
review AI detects when a customer names one, and analytics aggregate
per-employee performance. Mentions that match no registered employee are kept
with staff_member_id NULL (the unassigned bucket) until the owner resolves
them.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261112140000"
down_revision: Union[str, None] = "20261112130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS staff_members (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            listing_id VARCHAR(255) NOT NULL,
            name VARCHAR(120) NOT NULL,
            normalized_name VARCHAR(120) NOT NULL,
            aliases JSON DEFAULT '[]',
            active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_members_user_listing_name "
        "ON staff_members (user_id, listing_id, normalized_name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staff_members_user_listing "
        "ON staff_members (user_id, listing_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS review_staff_mentions (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            channel_id VARCHAR(36) NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
            review_id VARCHAR(500) NOT NULL,
            staff_member_id VARCHAR(36) REFERENCES staff_members(id) ON DELETE SET NULL,
            name_display VARCHAR(255) NOT NULL,
            name_normalized VARCHAR(120) NOT NULL,
            sentiment VARCHAR(20) NOT NULL DEFAULT 'neutral',
            rating INTEGER NOT NULL,
            review_created_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_staff_mentions_review_name "
        "ON review_staff_mentions (user_id, channel_id, review_id, name_normalized)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staff_mentions_user_staff_date "
        "ON review_staff_mentions (user_id, staff_member_id, review_created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staff_mentions_user_unmatched "
        "ON review_staff_mentions (user_id, name_normalized)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_staff_mentions_review "
        "ON review_staff_mentions (channel_id, review_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS review_staff_mentions")
    op.execute("DROP TABLE IF EXISTS staff_members")
