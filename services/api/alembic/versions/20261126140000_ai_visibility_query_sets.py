"""Add versioned business-aware AI visibility query sets."""
from alembic import op

revision = "20261126140000"
down_revision = "20261126120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_visibility_query_sets (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            channel_id VARCHAR(36) NOT NULL,
            version INTEGER NOT NULL,
            parent_query_set_id VARCHAR(36),
            status VARCHAR(24) NOT NULL DEFAULT 'generating',
            phase VARCHAR(40),
            depth VARCHAR(16) NOT NULL DEFAULT 'quick',
            job_id VARCHAR(36),
            classification_json JSON NOT NULL DEFAULT '{}',
            source_snapshot_json JSON NOT NULL DEFAULT '{}',
            generation_meta_json JSON NOT NULL DEFAULT '{}',
            total_questions INTEGER NOT NULL DEFAULT 0,
            completed_questions INTEGER NOT NULL DEFAULT 0,
            failed_questions INTEGER NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ai_visibility_query_set_version
                UNIQUE (tenant_id, channel_id, version),
            CONSTRAINT fk_ai_visibility_query_sets_parent
                FOREIGN KEY (parent_query_set_id)
                REFERENCES ai_visibility_query_sets(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_visibility_questions (
            id VARCHAR(36) PRIMARY KEY,
            query_set_id VARCHAR(36) NOT NULL,
            tenant_id VARCHAR(36) NOT NULL,
            channel_id VARCHAR(36) NOT NULL,
            question_key VARCHAR(40) NOT NULL,
            question_text TEXT NOT NULL,
            normalized_question_hash CHAR(64) NOT NULL,
            language VARCHAR(8) NOT NULL,
            customer_intent VARCHAR(80) NOT NULL,
            industry_relevance INTEGER NOT NULL,
            service_relevance INTEGER NOT NULL,
            geographic_context VARCHAR(255),
            business_relevance_score INTEGER NOT NULL,
            research_priority VARCHAR(4) NOT NULL,
            origin VARCHAR(16) NOT NULL DEFAULT 'initial',
            carried_from_question_id VARCHAR(36),
            prompt_id VARCHAR(36),
            run_id VARCHAR(36),
            status VARCHAR(24) NOT NULL DEFAULT 'pending',
            position INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ai_visibility_question_key
                UNIQUE (query_set_id, question_key),
            CONSTRAINT uq_ai_visibility_generated_question_hash
                UNIQUE (tenant_id, channel_id, normalized_question_hash),
            CONSTRAINT uq_ai_visibility_question_position
                UNIQUE (query_set_id, position),
            CONSTRAINT fk_ai_visibility_questions_set
                FOREIGN KEY (query_set_id)
                REFERENCES ai_visibility_query_sets(id) ON DELETE CASCADE,
            CONSTRAINT fk_ai_visibility_questions_carried
                FOREIGN KEY (carried_from_question_id)
                REFERENCES ai_visibility_questions(id) ON DELETE SET NULL,
            CONSTRAINT fk_ai_visibility_questions_prompt
                FOREIGN KEY (prompt_id)
                REFERENCES ai_visibility_prompts(id) ON DELETE SET NULL
        )
        """
    )
    op.execute(
        "ALTER TABLE ai_visibility_runs "
        "ADD COLUMN IF NOT EXISTS query_set_id VARCHAR(36)"
    )
    op.execute(
        "ALTER TABLE ai_visibility_runs "
        "ADD COLUMN IF NOT EXISTS question_id VARCHAR(36)"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_ai_visibility_runs_query_set'
            ) THEN
                ALTER TABLE ai_visibility_runs
                ADD CONSTRAINT fk_ai_visibility_runs_query_set
                FOREIGN KEY (query_set_id)
                REFERENCES ai_visibility_query_sets(id) ON DELETE SET NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_ai_visibility_runs_question'
            ) THEN
                ALTER TABLE ai_visibility_runs
                ADD CONSTRAINT fk_ai_visibility_runs_question
                FOREIGN KEY (question_id)
                REFERENCES ai_visibility_questions(id) ON DELETE SET NULL;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_query_sets_tenant_channel "
        "ON ai_visibility_query_sets (tenant_id, channel_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_visibility_one_active_query_set "
        "ON ai_visibility_query_sets (tenant_id, channel_id) "
        "WHERE status IN ('generating','running')"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_questions_tenant_channel "
        "ON ai_visibility_questions (tenant_id, channel_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_runs_query_set "
        "ON ai_visibility_runs (query_set_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_runs_question "
        "ON ai_visibility_runs (question_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_visibility_runs_question")
    op.execute("DROP INDEX IF EXISTS ix_ai_visibility_runs_query_set")
    op.execute(
        "ALTER TABLE ai_visibility_runs "
        "DROP CONSTRAINT IF EXISTS fk_ai_visibility_runs_question"
    )
    op.execute(
        "ALTER TABLE ai_visibility_runs "
        "DROP CONSTRAINT IF EXISTS fk_ai_visibility_runs_query_set"
    )
    op.execute(
        "ALTER TABLE ai_visibility_runs DROP COLUMN IF EXISTS question_id"
    )
    op.execute(
        "ALTER TABLE ai_visibility_runs DROP COLUMN IF EXISTS query_set_id"
    )
    op.execute("DROP TABLE IF EXISTS ai_visibility_questions")
    op.execute("DROP TABLE IF EXISTS ai_visibility_query_sets")
