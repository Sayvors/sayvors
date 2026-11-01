"""message_media

Inbound customer media (screenshots, receipts, PDFs) and outbound documents/
stickers need a private attachment beside the message row. The bytes live in
the private document store under `inbox-<tenant>`; the API serves them through
an authenticated route, never as a public media URL.

Revision ID: 3d9b7e1a5c204f86
Revises: f6a2d9c4e713805b
"""

from typing import Sequence, Union

from alembic import op

revision: str = "3d9b7e1a5c204f86"
down_revision: Union[str, None] = "f6a2d9c4e713805b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS media_key VARCHAR(300)"
    )
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS media_mime_type VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS media_filename VARCHAR(500)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS media_filename"
    )
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS media_mime_type"
    )
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS media_key"
    )
