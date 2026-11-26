"""Add an append-only AI visibility attempt ledger for rolling limits."""
from alembic import op

revision = "20261125130000"
down_revision = "20261125120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_visibility_attempts (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            prompt_id VARCHAR(36) NOT NULL
                REFERENCES ai_visibility_prompts(id) ON DELETE CASCADE,
            run_id VARCHAR(36) NOT NULL,
            attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ai_visibility_attempt_run UNIQUE (prompt_id, run_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_attempts_tenant_id "
        "ON ai_visibility_attempts (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_attempts_prompt_id "
        "ON ai_visibility_attempts (prompt_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_visibility_attempts_prompt_time "
        "ON ai_visibility_attempts (prompt_id, attempted_at)"
    )
    # Only the trailing hour can affect the rolling budget. Older history is
    # intentionally not imported, and ON CONFLICT makes a manual rerun harmless.
    op.execute(
        """
        INSERT INTO ai_visibility_attempts
            (id, tenant_id, prompt_id, run_id, attempted_at)
        SELECT id, tenant_id, prompt_id, id, created_at
        FROM ai_visibility_runs
        WHERE created_at >= now() - INTERVAL '1 hour'
        ON CONFLICT (prompt_id, run_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ai_visibility_attempts")
