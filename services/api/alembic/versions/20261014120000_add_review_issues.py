"""Add review_issues table.

Revision ID: 20261014120000
Revises: 20261014100000
Create Date: 2026-10-14

Stores the structured classification of every Google review: primary
category (12 fixed), tenant-specific subcategory, intent, sentiment,
priority, needs_attention flag, status lifecycle. One row per review.

Resolution reasons:
- Replaces rating-based gating in reviews_worker with needs_attention
- Powers the WhatsApp recovery handoff (Phase C)
- Backs the ticket-number and status surface for customer support
- Zero rows on a fresh install; defaults populate organically

Lock note: this table grows with reviews but has the same 1-to-1
cardinality as review_replies, so rollups scale linearly.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261014120000"
down_revision: Union[str, Sequence[str], None] = "20261014100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "review_issues",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("channel_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("review_reply_id", sa.String(length=36), nullable=True, index=True),
        sa.Column("review_id", sa.String(length=500), nullable=False, index=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("primary_category", sa.String(length=60), nullable=False, server_default="other"),
        sa.Column("subcategory", sa.String(length=100), nullable=False, server_default="other"),
        sa.Column("subcategory_detail", sa.String(length=255), nullable=True),
        # Defaults are members of review_engine.classification.INTENTS /
        # SENTIMENTS. "question" and "neutral" are not, so the originals here
        # produced rows that could never pass ReviewClassification.validate().
        sa.Column("intent", sa.String(length=40), nullable=False, server_default="ask_question"),
        sa.Column("sentiment", sa.String(length=20), nullable=False, server_default="mixed"),
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="normal"),
        sa.Column("needs_attention", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("reviewer_name", sa.String(length=255), nullable=True),
        sa.Column("review_text", sa.Text(), nullable=True),
        sa.Column("extractor_version", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_reply_id"], ["review_replies.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_review_issues_tenant_status", "review_issues", ["tenant_id", "status"])
    op.create_index("ix_review_issues_tenant_priority", "review_issues", ["tenant_id", "priority"])
    op.create_index("ix_review_issues_tenant_review_id", "review_issues", ["tenant_id", "review_id"])

def downgrade() -> None:
    op.drop_index("ix_review_issues_tenant_review_id", table_name="review_issues")
    op.drop_index("ix_review_issues_tenant_priority", table_name="review_issues")
    op.drop_index("ix_review_issues_tenant_status", table_name="review_issues")
    op.drop_table("review_issues")