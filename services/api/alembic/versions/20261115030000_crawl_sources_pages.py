"""crawl_sources + crawl_pages tables (§31 Phase 0)

Revision ID: 20261115030000
Revises: 20261115020000
Create Date: 2026-11-15

Upgrades the one-shot ScrapeJob crawler into a managed per-site sync system:

- ``crawl_sources`` — one row per tenant website: start URL, scope, page cap,
  sync toggle/interval, next/last sync, last status.
- ``crawl_pages`` — one row per discovered page: status, conditional-GET
  validators (ETag/Last-Modified), content hash for change detection, and the
  ingested ``Document`` id. The (source_id, url) unique index enforces upsert
  semantics — the duplicate-document bug fix.

All DDL is ``IF NOT EXISTS`` so a partially applied deploy re-runs safely.
String columns (not Postgres enums) keep the migration free of type-creation
ordering issues, consistent with the other recent tables.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261115030000"
down_revision: Union[str, None] = "20261115020000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crawl_sources (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            databank_id VARCHAR(36) NOT NULL
                REFERENCES databanks (id),
            start_url VARCHAR(2000) NOT NULL,
            scope VARCHAR(16) NOT NULL DEFAULT 'subtree',
            max_pages INTEGER NOT NULL DEFAULT 200,
            sync_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            sync_interval_minutes INTEGER NOT NULL DEFAULT 60,
            next_sync_at TIMESTAMPTZ,
            last_sync_at TIMESTAMPTZ,
            last_status VARCHAR(20) NOT NULL DEFAULT 'idle',
            error TEXT,
            created_by VARCHAR(36),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT crawl_sources_interval_floor
                CHECK (sync_interval_minutes >= 60),
            CONSTRAINT crawl_sources_max_pages_bounds
                CHECK (max_pages >= 1 AND max_pages <= 500)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crawl_sources_user "
        "ON crawl_sources (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crawl_sources_databank "
        "ON crawl_sources (databank_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crawl_sources_next_sync "
        "ON crawl_sources (next_sync_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS crawl_pages (
            id VARCHAR(36) PRIMARY KEY,
            source_id VARCHAR(36) NOT NULL
                REFERENCES crawl_sources (id) ON DELETE CASCADE,
            url VARCHAR(2000) NOT NULL,
            title VARCHAR(500),
            status VARCHAR(16) NOT NULL DEFAULT 'discovered',
            http_etag VARCHAR(300),
            http_last_modified VARCHAR(300),
            content_hash VARCHAR(64),
            lang VARCHAR(8),
            word_count INTEGER NOT NULL DEFAULT 0,
            fetched_at TIMESTAMPTZ,
            document_id VARCHAR(36) REFERENCES documents (id),
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_crawl_pages_source_url "
        "ON crawl_pages (source_id, url)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crawl_pages_source_status "
        "ON crawl_pages (source_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crawl_pages_content_hash "
        "ON crawl_pages (content_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crawl_pages_document "
        "ON crawl_pages (document_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS crawl_pages")
    op.execute("DROP TABLE IF EXISTS crawl_sources")
