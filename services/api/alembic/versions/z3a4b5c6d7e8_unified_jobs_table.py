"""unified jobs table

Revision ID: z3a4b5c6d7e8
Revises: z2a3b4c5d6e7
Create Date: 2026-10-17

Single source of truth for job execution lifecycle. Postgres owns whether and
when a job runs; Kafka owns dispatch only; Redis owns ephemeral admission
control. See docs/specs/2026-10-10-unified-job-processing-design.md §C.2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'z3a4b5c6d7e8'
down_revision: Union[str, None] = 'z2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'jobs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('tenant_id', sa.String(length=36), nullable=False),
        sa.Column('job_type', sa.String(length=100), nullable=False),
        sa.Column('lane', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('idempotency_key', sa.String(length=200), nullable=True),
        sa.Column('subject_type', sa.String(length=50), nullable=True),
        sa.Column('subject_id', sa.String(length=36), nullable=True),
        sa.Column('lane_key', sa.String(length=64), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lease_owner', sa.String(length=64), nullable=True),
        sa.Column('external_intent', sa.JSON(), nullable=True),
        sa.Column('external_result', sa.JSON(), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'tenant_id', 'idempotency_key',
            name='uq_jobs_tenant_idempotency',
        ),
    )
    op.create_index(op.f('ix_jobs_tenant_id'), 'jobs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_index(op.f('ix_jobs_lane'), 'jobs', ['lane'], unique=False)
    op.create_index(op.f('ix_jobs_next_run_at'), 'jobs', ['next_run_at'], unique=False)
    op.create_index(op.f('ix_jobs_due'), 'jobs', ['status', 'next_run_at'], unique=False)
    op.create_index(
        op.f('ix_jobs_lane_due'), 'jobs', ['lane', 'status', 'next_run_at'], unique=False
    )
    op.create_index(
        op.f('ix_jobs_lease'), 'jobs', ['status', 'lease_expires_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_jobs_lease'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_lane_due'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_due'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_next_run_at'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_lane'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_tenant_id'), table_name='jobs')
    op.drop_table('jobs')
