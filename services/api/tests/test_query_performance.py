"""Query-performance indexes are part of the schema contract.

Every index here exists because a specific hot query was measured against a
table that grows with tenants. They are easy to lose: a model edit that
rebuilds ``__table_args__``, a migration that never lands, or a table rename
silently drops the index and the query goes back to a sequential scan.

The migration creates the same indexes CONCURRENTLY; this test keeps the
models (which build the SQLite test schema) in step with it.
"""
import app.main  # noqa: F401 - imports every model into Base.metadata
from app.database import Base

# (table, index, expected leading columns)
EXPECTED_INDEXES = [
    # Missing FK indexes: Postgres indexes PKs, not FKs.
    ("ingest_jobs", "ix_ingest_jobs_databank_id", ["databank_id"]),
    ("ingest_jobs", "ix_ingest_jobs_document_id", ["document_id"]),
    ("scrape_jobs", "ix_scrape_jobs_databank_id", ["databank_id"]),
    ("meta_assets", "ix_meta_assets_parent_asset_id", ["parent_asset_id"]),
    ("tts_jobs", "ix_tts_jobs_voice_id", ["voice_id"]),
    # Inbox search reads the newest slice of one channel.
    (
        "channel_messages",
        "ix_channel_messages_channel_created",
        ["channel_id", "created_at"],
    ),
    # Retention sweeps delete by status + age.
    ("jobs", "ix_jobs_status_created", ["status", "created_at"]),
    ("event_outbox", "ix_event_outbox_status_created", ["status", "created_at"]),
    (
        "meta_webhook_events",
        "ix_meta_webhook_events_status_created",
        ["status", "created_at"],
    ),
    ("notifications", "ix_notifications_read_created", ["created_at"]),
    # Analytics reads filter one tenant and a date range, ordered by date.
    (
        "location_daily_metrics",
        "ix_location_daily_metrics_user_date",
        ["user_id", "date"],
    ),
    (
        "channel_daily_metrics",
        "ix_channel_daily_metrics_user_date",
        ["user_id", "date"],
    ),
    (
        "search_keyword_stats",
        "ix_search_keyword_stats_user_date",
        ["user_id", "date"],
    ),
    ("review_insights", "ix_review_insights_user_created", ["user_id", "created_at"]),
]


def test_critical_query_indexes_exist():
    missing = []
    wrong_columns = []
    for table_name, index_name, expected_columns in EXPECTED_INDEXES:
        table = Base.metadata.tables.get(table_name)
        assert table is not None, f"table {table_name} is not in the metadata"
        index = next((i for i in table.indexes if i.name == index_name), None)
        if index is None:
            missing.append(f"{table_name}.{index_name}")
            continue
        actual = [column.name for column in index.columns]
        if actual != expected_columns:
            wrong_columns.append(
                f"{table_name}.{index_name}: {actual} != {expected_columns}"
            )

    assert not missing, "missing query indexes: " + ", ".join(missing)
    assert not wrong_columns, "indexes on wrong columns: " + ", ".join(wrong_columns)
