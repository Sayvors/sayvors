"""Add grounded AI visibility research tables and job type."""
from alembic import op

revision = "20261125120000"
down_revision = "20261124110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'ai_visibility.research'")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_visibility_prompts (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            channel_id VARCHAR(36) NOT NULL,
            title VARCHAR(200) NOT NULL,
            prompt_text TEXT NOT NULL,
            normalized_prompt_hash CHAR(64) NOT NULL,
            intent VARCHAR(80) NOT NULL DEFAULT 'custom',
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_by VARCHAR(36) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ai_visibility_prompt_branch_hash
                UNIQUE (tenant_id, channel_id, normalized_prompt_hash)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_visibility_runs (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            channel_id VARCHAR(36) NOT NULL,
            prompt_id VARCHAR(36) NOT NULL REFERENCES ai_visibility_prompts(id) ON DELETE RESTRICT,
            prompt_snapshot TEXT NOT NULL,
            locale VARCHAR(8) NOT NULL DEFAULT 'en',
            status VARCHAR(24) NOT NULL DEFAULT 'queued',
            job_id VARCHAR(36),
            search_provider VARCHAR(40),
            model VARCHAR(255),
            answer_text TEXT,
            mentioned BOOLEAN,
            cited BOOLEAN,
            recommended BOOLEAN,
            incorrect BOOLEAN,
            validation_status VARCHAR(16) NOT NULL DEFAULT 'pending',
            evidence_coverage JSON NOT NULL DEFAULT '{}'::json,
            source_count INTEGER NOT NULL DEFAULT 0,
            validated_claim_count INTEGER NOT NULL DEFAULT 0,
            unsupported_claim_count INTEGER NOT NULL DEFAULT 0,
            competitor_mentions JSON NOT NULL DEFAULT '[]'::json,
            claims_json JSON NOT NULL DEFAULT '[]'::json,
            actions_json JSON NOT NULL DEFAULT '[]'::json,
            error TEXT,
            failure_code VARCHAR(80),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_visibility_sources (
            id VARCHAR(36) PRIMARY KEY,
            run_id VARCHAR(36) NOT NULL REFERENCES ai_visibility_runs(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            url VARCHAR(2048) NOT NULL,
            canonical_url VARCHAR(2048) NOT NULL,
            title VARCHAR(500),
            snippet TEXT,
            excerpt TEXT,
            content_hash CHAR(64),
            http_status INTEGER,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            fetch_error TEXT,
            CONSTRAINT uq_ai_visibility_source_position UNIQUE (run_id, position)
        )
        """
    )
    statements = (
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_prompts_tenant_id ON ai_visibility_prompts (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_prompts_channel_id ON ai_visibility_prompts (channel_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_prompts_tenant_channel ON ai_visibility_prompts (tenant_id, channel_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_runs_tenant_id ON ai_visibility_runs (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_runs_channel_id ON ai_visibility_runs (channel_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_runs_tenant_created ON ai_visibility_runs (tenant_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_runs_channel_status ON ai_visibility_runs (channel_id, status)",
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_sources_run_id ON ai_visibility_sources (run_id)",
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_visibility_one_active_run
           ON ai_visibility_runs (tenant_id, prompt_id)
           WHERE status IN ('queued','searching','fetching','reading','validating','writing')""",
    )
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_visibility_sources")
    op.execute("DROP TABLE IF EXISTS ai_visibility_runs")
    op.execute("DROP TABLE IF EXISTS ai_visibility_prompts")
