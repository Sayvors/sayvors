"""ai_personas

Named customer-facing personas. The admin picks one active persona; the reply
prompt reads it instead of hard-coding "Sarah". Sarah is seeded as the default
so existing tenants keep the same assistant.

Revision ID: f5a8c2d6e9b14370
Revises: c9b2e7f4a1d65830
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f5a8c2d6e9b14370"
down_revision: Union[str, None] = "c9b2e7f4a1d65830"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_personas (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(80) NOT NULL,
            gender VARCHAR(16) NOT NULL DEFAULT 'female',
            description VARCHAR(255),
            instructions TEXT,
            is_active BOOLEAN NOT NULL DEFAULT FALSE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_ai_personas_name "
        "ON ai_personas (name)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ai_personas_active "
        "ON ai_personas (is_active)"
    )
    op.execute(
        """
        INSERT INTO ai_personas
            (id, name, gender, description, instructions, is_active, sort_order)
        SELECT
            '00000000-0000-0000-0000-000000000001',
            'Sarah',
            'female',
            'Warm, capable support teammate',
            NULL,
            TRUE,
            0
        WHERE NOT EXISTS (SELECT 1 FROM ai_personas)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_personas_active")
    op.execute("DROP INDEX IF EXISTS ix_ai_personas_name")
    op.execute("DROP TABLE IF EXISTS ai_personas")
