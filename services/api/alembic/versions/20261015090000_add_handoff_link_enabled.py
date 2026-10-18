"""Add auto_reply_configs.handoff_link_enabled.

Revision ID: 20261015090000
Revises: 20261014130000
Create Date: 2026-10-15

Tenant opt-out for the review -> WhatsApp handoff link. Needs-attention
reviews get a wa.me deep link (prefilled with the issue's handoff code)
appended to the public reply; the link necessarily publishes the tenant's
WhatsApp number on the listing, so tenants must be able to turn it off.
Default ON (server-side too) because the recovery loop is the point of the
feature; existing rows adopt it without a data migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261015090000"
down_revision: Union[str, Sequence[str], None] = "20261014130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        "auto_reply_configs",
        sa.Column("handoff_link_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
    )

def downgrade() -> None:
    op.drop_column("auto_reply_configs", "handoff_link_enabled")
