"""Add UI progress fields to jobs.

Revision ID: 20261122100000
Revises: 20261121140000
Create Date: 2026-11-22

Phase 1 of background-operation progress UI: store progress/UI metadata on the
unified jobs table and expose tenant-scoped active UI jobs. No behavior change
for existing jobs; all new columns are nullable/defaulted.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20261122100000"
down_revision = "20261121140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("progress_label", sa.String(length=120), nullable=True))
    op.add_column("jobs", sa.Column("ui_title", sa.String(length=200), nullable=True))
    op.add_column("jobs", sa.Column("ui_kind", sa.String(length=50), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("ui_visible", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("jobs", sa.Column("ui_subject_type", sa.String(length=50), nullable=True))
    op.add_column("jobs", sa.Column("ui_subject_id", sa.String(length=36), nullable=True))
    op.create_index("ix_jobs_tenant_ui_visible", "jobs", ["tenant_id", "ui_visible"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_tenant_ui_visible", table_name="jobs")
    op.drop_column("jobs", "ui_subject_id")
    op.drop_column("jobs", "ui_subject_type")
    op.drop_column("jobs", "ui_visible")
    op.drop_column("jobs", "ui_kind")
    op.drop_column("jobs", "ui_title")
    op.drop_column("jobs", "progress_label")
    op.drop_column("jobs", "progress")
