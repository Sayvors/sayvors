"""whatsapp_qr_codes

Local click-to-chat QR codes. The previous implementation called Meta's
`message_qrdls` endpoint, which needs `whatsapp_business_management`; when the
connection token lacked it the settings page failed with an opaque "Failed to
fetch". A `wa.me/<number>?text=<message>` link needs no permission and never
expires, so the code is generated and stored here. The QR image is rendered in
the browser from `deep_link_url`.

Revision ID: a1f4c8e2d9b7035
Revises: 7c2f9b4e1d6a8035
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a1f4c8e2d9b7035"
down_revision: Union[str, None] = "7c2f9b4e1d6a8035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS whatsapp_qr_codes (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            channel_id VARCHAR(36) NOT NULL
                REFERENCES channels(id) ON DELETE CASCADE,
            code VARCHAR(16) NOT NULL,
            prefilled_message VARCHAR(140) NOT NULL,
            deep_link_url TEXT NOT NULL,
            created_by VARCHAR(36),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_whatsapp_qr_codes_tenant_id "
        "ON whatsapp_qr_codes (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_whatsapp_qr_channel "
        "ON whatsapp_qr_codes (channel_id, created_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_whatsapp_qr_tenant_code "
        "ON whatsapp_qr_codes (tenant_id, code)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_whatsapp_qr_tenant_code")
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_qr_channel")
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_qr_codes_tenant_id")
    op.execute("DROP TABLE IF EXISTS whatsapp_qr_codes")
