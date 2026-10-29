"""channel_bridges plus leads.merged_into_id

The Instagram -> WhatsApp move needs a durable link between the Instagram
lead and the first WhatsApp inbound: WhatsApp forbids business-initiated
messages outside a 24h window, so the customer has to arrive themselves.

``leads.merged_into_id`` marks a lead consolidated into another channel's
lead. The row and its thread stay (history is real), but the pipeline works
the surviving lead — the list and digest skip merged rows.

Revision ID: 2cb0d67d62f0
Revises: 799b1be10d2c
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "2cb0d67d62f0"
down_revision = "799b1be10d2c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_bridges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "channel_id",
            sa.String(36),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contact_id", sa.String(64), nullable=False),
        sa.Column("phone_e164", sa.String(32), nullable=False),
        sa.Column("token", sa.String(16), nullable=False),
        sa.Column("target_asset_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_lead_id", sa.String(36), nullable=True),
    )
    # Unique: a token must identify exactly one bridge globally, or matching
    # would depend on which tenant happened to arrive first.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_bridges_token "
        "ON channel_bridges (token)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_bridges_tenant_phone "
        "ON channel_bridges (tenant_id, phone_e164)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_bridges_source "
        "ON channel_bridges (channel_id, contact_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_bridges_tenant_id "
        "ON channel_bridges (tenant_id)"
    )

    # Soft pointer, deliberately not a FK: deleting the surviving lead must not
    # be blocked by, or cascade into, the merged history row.
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS merged_into_id varchar(36)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leads_merged_into_id "
        "ON leads (merged_into_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_leads_merged_into_id")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS merged_into_id")
    op.drop_table("channel_bridges")
