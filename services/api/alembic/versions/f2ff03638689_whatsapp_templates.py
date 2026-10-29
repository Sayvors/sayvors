"""whatsapp_templates, template_sends, leads consent columns

Outside the 24-hour customer-service window Meta rejects free-form messages;
only a pre-approved template can be sent. These tables mirror the WABA's
templates, keep every send attempt, and record the consent basis the send
relied on.

Revision ID: f2ff03638689
Revises: 3f20388db8a7
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "f2ff03638689"
down_revision = "3f20388db8a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("language", sa.String(20), nullable=False, server_default="en"),
        sa.Column("category", sa.String(20), nullable=False, server_default="utility"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("variables", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("meta_template_id", sa.String(64), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "name", "language",
            name="uq_whatsapp_templates_name_lang",
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_whatsapp_templates_tenant_id "
        "ON whatsapp_templates (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_whatsapp_templates_tenant_status "
        "ON whatsapp_templates (tenant_id, status)"
    )

    op.create_table(
        "template_sends",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("lead_id", sa.String(36), nullable=True),
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("whatsapp_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("contact_phone", sa.String(32), nullable=False),
        sa.Column("template_name", sa.String(200), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="sent"),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_by", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_template_sends_idempotency"
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_template_sends_tenant_id "
        "ON template_sends (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_template_sends_tenant_created "
        "ON template_sends (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_template_sends_lead "
        "ON template_sends (lead_id, created_at)"
    )

    # Consent basis. NULL opt_in_at means "no basis": templates are refused.
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_opt_in_at timestamptz")
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_opt_in_source varchar(32)"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS whatsapp_opt_in_message_id varchar(200)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS whatsapp_opt_in_message_id")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS whatsapp_opt_in_source")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS whatsapp_opt_in_at")
    op.drop_table("template_sends")
    op.drop_table("whatsapp_templates")
