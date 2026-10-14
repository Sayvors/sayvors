"""Add ticket_number and handoff_code to review_issues.

Revision ID: 20261014130000
Revises: 20261014120000
Create Date: 2026-10-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261014130000"
down_revision: Union[str, Sequence[str], None] = "20261014120000"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("review_issues", sa.Column("ticket_number", sa.String(length=20), nullable=True))
    op.add_column("review_issues", sa.Column("handoff_code", sa.String(length=16), nullable=True))
    op.create_index("ix_review_issues_tenant_ticket", "review_issues", ["tenant_id", "ticket_number"], unique=True)
    op.create_index("ix_review_issues_handoff_code", "review_issues", ["handoff_code"], unique=True)

def downgrade() -> None:
    op.drop_index("ix_review_issues_handoff_code", table_name="review_issues")
    op.drop_index("ix_review_issues_tenant_ticket", table_name="review_issues")
    op.drop_column("review_issues", "handoff_code")
    op.drop_column("review_issues", "ticket_number")