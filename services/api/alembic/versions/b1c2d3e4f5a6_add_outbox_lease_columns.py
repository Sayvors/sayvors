"""add lease columns to event_outbox

Inbound meta events are claimed by setting status='processing'. Without
lease columns, a worker crash mid-processing leaves the event stuck in
'processing' forever (lost message). lease_owner + lease_expires_at let
_claim_due_events reclaim expired leases, mirroring the JobRunner pattern.

Revision ID: b1c2d3e4f5a6
Revises: 7a8b9c0d1e2f
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = '7a8b9c0d1e2f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'event_outbox',
        sa.Column('lease_owner', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'event_outbox',
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_event_outbox_lease_expires',
        'event_outbox',
        ['lease_expires_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_event_outbox_lease_expires', table_name='event_outbox')
    op.drop_column('event_outbox', 'lease_expires_at')
    op.drop_column('event_outbox', 'lease_owner')
