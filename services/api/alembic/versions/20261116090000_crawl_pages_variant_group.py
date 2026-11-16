"""crawl_pages/documents: variant_group + lang for EN/AR pairing (§31 Phase A)

Revision ID: 20261116090000
Revises: 20261115030000
Create Date: 2026-11-16

Adds the language-variant grouping columns:

- ``crawl_pages.variant_group`` / ``crawl_pages.lang``
- ``documents.variant_group`` / ``documents.lang``

``variant_group`` is the language-neutral page identity (crawler.variant_group):
``/en/pricing`` and ``ar/pricing`` both map to ``/pricing`` so hreflang twins
group as one knowledge item instead of looking like duplicate crawls.
``lang`` is the content language (URL prefix first, detected script fallback).

Both are nullable: existing rows keep working; backfill happens lazily on the
next crawl or via the recovery script. Idempotent DDL like the rest of §31.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261116090000"
down_revision: Union[str, None] = "20261115030000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS variant_group VARCHAR(2000)"
    )
    op.execute(
        "ALTER TABLE crawl_pages ADD COLUMN IF NOT EXISTS lang VARCHAR(8)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crawl_pages_variant_group "
        "ON crawl_pages (variant_group)"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS lang VARCHAR(8)"
    )
    op.execute(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS variant_group VARCHAR(2000)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_variant_group "
        "ON documents (variant_group)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_variant_group")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS variant_group")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS lang")
    op.execute("DROP INDEX IF EXISTS ix_crawl_pages_variant_group")
    op.execute("ALTER TABLE crawl_pages DROP COLUMN IF EXISTS lang")
    op.execute("ALTER TABLE crawl_pages DROP COLUMN IF EXISTS variant_group")

