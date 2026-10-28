"""Pin the schema facts that make the models the database source of truth.

These tests do not need a live PostgreSQL: they assert what
``Base.metadata.create_all`` would build. The PostgreSQL-only indexes are
registered as after_create hooks and are covered by the fresh-rebuild probe,
not by the SQLite test database.
"""
from sqlalchemy.dialects import postgresql

from app.config import settings
from app.database import Base
from app.modules.channels.models import ReviewIssue, WhatsAppThreadState
from app.modules.rag.models import EmbeddingVector
from app.modules.review_engine.csv_models import CSVRow


def _index(table_name: str, index_name: str):
    table = Base.metadata.tables[table_name]
    for index in table.indexes:
        if index.name == index_name:
            return index
    raise AssertionError(f"{index_name} is not declared on {table_name}")


def test_csv_models_are_registered_in_metadata():
    # Without the side-effect import in review_engine/models.py, Alembic
    # autogenerate would propose dropping these tables and a models-only
    # rebuild would omit them.
    assert "csv_uploads" in Base.metadata.tables
    assert "csv_rows" in Base.metadata.tables


def test_review_issue_handoff_code_is_globally_unique():
    index = _index("review_issues", "ix_review_issues_handoff_code")
    assert index.unique is True
    assert [column.name for column in index.columns] == ["handoff_code"]


def test_review_issue_tenant_ticket_is_unique():
    index = _index("review_issues", "ix_review_issues_tenant_ticket")
    assert index.unique is True
    assert [column.name for column in index.columns] == ["tenant_id", "ticket_number"]


def test_review_issue_queue_indexes_are_declared():
    expected = {
        "ix_review_issues_tenant_status": ["tenant_id", "status"],
        "ix_review_issues_tenant_priority": ["tenant_id", "priority"],
        "ix_review_issues_tenant_review_id": ["tenant_id", "review_id"],
        "ix_review_issues_needs_attention": ["needs_attention"],
    }
    for name, columns in expected.items():
        index = _index("review_issues", name)
        assert [column.name for column in index.columns] == columns


def test_whatsapp_contact_phone_matches_the_not_null_column():
    table = Base.metadata.tables["whatsapp_thread_states"]
    assert table.c.contact_phone.nullable is False
    assert table.c.contact_phone_hash.nullable is True


def test_whatsapp_index_names_match_the_migrated_database():
    table = Base.metadata.tables["whatsapp_thread_states"]
    names = {index.name for index in table.indexes}
    assert {
        "ix_wa_thread_states_channel_id",
        "ix_wa_thread_states_contact_phone",
        "ix_wa_thread_states_contact_phone_hash",
    } <= names


def test_event_outbox_has_no_dead_lease_columns():
    columns = set(Base.metadata.tables["event_outbox"].columns.keys())
    assert columns.isdisjoint(
        {"worker_id", "claimed_at", "claimed_until", "processing_started_at"}
    )


def test_csv_rows_data_is_jsonb_on_postgres():
    # csv_service uses @> and jsonb_each_text(), which plain JSON does not
    # support. A models-only rebuild must still produce JSONB.
    pg_type = CSVRow.__table__.c.data.type.dialect_impl(postgresql.dialect())
    assert pg_type.__class__.__name__.upper().endswith("JSONB")


def test_index_names_shared_with_migrations_are_declared():
    expected = {
        "channel_threads": {
            "uq_channel_threads_channel_contact",
            "ix_channel_threads_channel_last",
        },
        "channel_comments": {
            "uq_channel_comments_platform_id",
            "ix_channel_comments_platform_id",
        },
        "platform_operators": {"ix_platform_operators_username"},
        "conversation_insights": {"ix_conversation_insights_tenant_window"},
        "market_benchmarks": {"ix_market_benchmarks_date_scope"},
        "billing_events": {"uq_billing_events_tenant_idempotency"},
        "event_outbox": {"ix_event_outbox_lease_expires"},
        "jobs": {"ix_jobs_hard_deadline"},
        "job_lane_heartbeats": {"ix_job_lane_heartbeats_last_seen"},
        "location_issues": {"ix_location_issues_user_channel_status"},
        # PostgreSQL-only indexes (partial/expression/GIN) are registered as
        # after_create hooks, not in table.indexes; the rebuild probe covers
        # them: ix_leads_pending_reminder, ix_review_insights_meaning_*,
        # ix_document_chunks_content_gin, idx_csv_rows_data.
    }
    for table_name, names in expected.items():
        table = Base.metadata.tables[table_name]
        declared = {index.name for index in table.indexes}
        assert names <= declared, f"{table_name} is missing {names - declared}"


def test_comment_platform_id_uniqueness_is_partial():
    # NULL platform ids are unsent drafts and may repeat; only real platform
    # ids are unique. The migration encodes that as a partial unique index.
    index = _index("channel_comments", "uq_channel_comments_platform_id")
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None


def test_message_platform_id_uniqueness_is_partial():
    # Replay dedupe: a real platform message id is unique, but NULL is
    # legitimate and may repeat. A plain index=True would lose the guarantee.
    index = _index("channel_messages", "ix_channel_messages_platform_message_id")
    assert index.unique is True
    assert index.dialect_options["postgresql"]["where"] is not None


def test_team_member_user_id_is_unique():
    # One workspace per user. The migrated database only had a plain index;
    # the parity migration makes it unique.
    index = _index("team_members", "ix_team_members_user_id")
    assert index.unique is True
    assert [column.name for column in index.columns] == ["user_id"]


def test_channel_daily_metric_cascades_on_channel_delete():
    # Deleting a channel must remove its rollups; without ON DELETE CASCADE
    # the foreign key blocks the delete once the channel has metrics.
    table = Base.metadata.tables["channel_daily_metrics"]
    foreign_key = next(iter(table.c.channel_id.foreign_keys))
    assert foreign_key.ondelete == "CASCADE"


def test_operator_username_keeps_the_migrated_unique_constraint():
    table = Base.metadata.tables["platform_operators"]
    assert table.c.username.unique is True


def test_columns_nullable_in_the_migrated_database_stay_nullable():
    # These columns were created without NOT NULL. Tightening them in the
    # model would make a models-only rebuild stricter than the deployed
    # schema; the Python defaults still populate them on every ORM insert.
    expected_nullable = {
        "csv_rows": ["created_at", "upload_id"],
        "csv_uploads": ["created_at", "row_count"],
        "response_strategies": ["created_at", "enabled", "priority", "updated_at"],
        "review_insights": ["abuse_labels", "media"],
        "review_intelligence_reports": ["competitive", "dimensions", "scope_key"],
        "review_response_logs": ["created_at", "status"],
    }
    for table_name, columns in expected_nullable.items():
        table = Base.metadata.tables[table_name]
        for column in columns:
            assert table.c[column].nullable is True, f"{table_name}.{column}"


def test_reply_model_has_no_hardcoded_server_default():
    # NULL means "tenant default, resolved from the admin-managed enabled
    # models". The original 'openai:gpt-4o-mini' server default filled the
    # column on every insert that omitted it; the parity migration drops it.
    column = Base.metadata.tables["auto_reply_configs"].c.model
    assert column.server_default is None
    assert column.nullable is True


def test_embedding_vector_is_pgvector_only_when_embeddings_are_enabled(monkeypatch):
    # The migration has two branches: VECTOR(1024) when embeddings are on,
    # TEXT otherwise. The model must mirror both, or a models-only rebuild on
    # a host without pgvector fails on a supported configuration.
    pg = postgresql.dialect()

    monkeypatch.setattr(settings, "EMBEDDINGS_ENABLED", True)
    enabled_impl = EmbeddingVector().dialect_impl(pg).impl
    assert enabled_impl.compile(dialect=pg) == "VECTOR(1024)"

    monkeypatch.setattr(settings, "EMBEDDINGS_ENABLED", False)
    disabled_impl = EmbeddingVector().dialect_impl(pg).impl
    assert disabled_impl.compile(dialect=pg) == "TEXT"


def test_embedding_vector_text_fallback_round_trips(monkeypatch):
    # With embeddings off the column is TEXT, so the type itself has to
    # serialize the list — otherwise SQLite/psycopg receive a Python list.
    monkeypatch.setattr(settings, "EMBEDDINGS_ENABLED", False)
    pg = postgresql.dialect()
    embedding = EmbeddingVector()

    stored = embedding.process_bind_param([1.0, 2.0], pg)
    assert stored == "[1.0,2.0]"
    assert embedding.process_result_value(stored, pg) == [1.0, 2.0]


def test_postgres_only_indexes_are_registered_for_autogenerate():
    # The hook-created indexes are invisible to Base.metadata, so their names
    # must be registered or a routine autogenerate would propose dropping them.
    from app.db_indexes import managed_postgres_index_names

    assert {
        "ix_leads_pending_reminder",
        "ix_review_insights_meaning_needs_human",
        "ix_review_insights_meaning_subject",
        "ix_document_chunks_content_gin",
        "ix_document_chunks_embedding_vector_hnsw",
        "idx_csv_rows_data",
    } <= managed_postgres_index_names()


def test_models_declare_every_application_table():
    # The migrated database has 72 application tables (plus alembic_version).
    # A models-only rebuild must not silently omit any of them.
    assert len(Base.metadata.tables) >= 72
    assert "alembic_version" not in Base.metadata.tables


def test_review_issue_and_thread_state_models_are_the_expected_classes():
    assert ReviewIssue.__tablename__ == "review_issues"
    assert WhatsAppThreadState.__tablename__ == "whatsapp_thread_states"
