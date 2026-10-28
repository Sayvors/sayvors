"""Query-performance indexes for 1M-tenant scale.

Four groups, each tied to a query that runs on a hot path:

1. Foreign keys. Postgres indexes primary keys, not foreign keys. Five FK
   columns had no index, so deleting a databank/document/voice/asset or
   listing its children scanned the whole table.
2. Inbox search. Message bodies are encrypted at rest, so search reads a
   bounded newest-first slice per channel. Without
   ``(channel_id, created_at)`` that slice sorts the channel's entire history
   on every keystroke.
3. Retention sweeps. The hourly cleanup deletes by status + age; the claim
   indexes are ordered by ``next_run_at`` and cannot serve it.
4. Analytics reads. Every report filters one tenant and a date range and
   orders by date. Two single-column indexes forced a sort of all the
   tenant's rows; the composites serve filter and ORDER BY together.

All indexes are built CONCURRENTLY. On a live table a plain CREATE INDEX
holds a write lock for the whole build; at 1M tenants that is a visible
outage. CONCURRENTLY takes longer but never blocks writes. It cannot run
inside a transaction, hence the autocommit block.

Every statement is IF NOT EXISTS so the migration is re-runnable after a
partial failure (a cancelled CONCURRENTLY build leaves no valid index).
"""
from alembic import op

revision = "c4d5e6f7a8b9c0"
down_revision = "a2b3c4d5e6f7a8b9"
branch_labels = None
depends_on = None


# (index name, table, column list, optional WHERE predicate)
_INDEXES: tuple[tuple[str, str, str, str | None], ...] = (
    # 1. Missing foreign-key indexes.
    ("ix_ingest_jobs_databank_id", "ingest_jobs", "databank_id", None),
    ("ix_ingest_jobs_document_id", "ingest_jobs", "document_id", None),
    ("ix_scrape_jobs_databank_id", "scrape_jobs", "databank_id", None),
    ("ix_meta_assets_parent_asset_id", "meta_assets", "parent_asset_id", None),
    ("ix_tts_jobs_voice_id", "tts_jobs", "voice_id", None),
    # 2. Inbox search: newest-first slice of one channel.
    ("ix_channel_messages_channel_created", "channel_messages", "channel_id, created_at", None),
    # 3. Retention sweeps: status + age.
    ("ix_jobs_status_created", "jobs", "status, created_at", None),
    ("ix_event_outbox_status_created", "event_outbox", "status, created_at", None),
    (
        "ix_meta_webhook_events_status_created",
        "meta_webhook_events",
        "status, created_at",
        None,
    ),
    (
        "ix_notifications_read_created",
        "notifications",
        "created_at",
        "read_at IS NOT NULL",
    ),
    # 4. Analytics: tenant + date range, ordered by date.
    (
        "ix_location_daily_metrics_user_date",
        "location_daily_metrics",
        "user_id, date",
        None,
    ),
    (
        "ix_channel_daily_metrics_user_date",
        "channel_daily_metrics",
        "user_id, date",
        None,
    ),
    (
        "ix_search_keyword_stats_user_date",
        "search_keyword_stats",
        "user_id, date",
        None,
    ),
    ("ix_review_insights_user_created", "review_insights", "user_id, created_at", None),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, table, columns, predicate in _INDEXES:
            where = f" WHERE {predicate}" if predicate else ""
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                f"ON {table} ({columns}){where}"
            )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _table, _columns, _predicate in reversed(_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
