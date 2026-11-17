"""Business-intake vertical + merchant-owned answers.

Adds a canonical ``vertical_key`` to users (the old ``business_type`` label is
kept for display) and the ``tenant_intake_answers`` table that stores the
owner's cascade answers. All DDL is idempotent so a staging re-run is safe.

Revision ID: 20261117110000
Revises: 20261117100000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261117110000"
down_revision: Union[str, None] = "20261117100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS vertical_key VARCHAR(40)"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS intake_sub_focus VARCHAR(40)"
    )
    op.execute(
        "UPDATE users SET vertical_key = CASE lower(coalesce(business_type, '')) "
        "WHEN 'e-commerce' THEN 'ecommerce' "
        "WHEN 'non-profit' THEN 'non_profit' "
        "WHEN 'ai / saas / software' THEN 'saas' "
        "WHEN 'bank / finance' THEN 'bank' "
        "WHEN 'food & restaurant' THEN 'restaurant' "
        "WHEN 'cafe & bakery' THEN 'cafe' "
        "WHEN 'retail & shops' THEN 'retail' "
        "WHEN 'healthcare & clinics' THEN 'healthcare' "
        "WHEN 'beauty & salon' THEN 'beauty' "
        "WHEN 'gym & fitness' THEN 'fitness' "
        "WHEN 'media / content' THEN 'media' "
        "WHEN 'professional services' THEN 'professional' "
        "ELSE lower(business_type) END "
        "WHERE vertical_key IS NULL AND business_type IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_intake_answers (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vertical_key VARCHAR(40) NOT NULL,
            question_key VARCHAR(80) NOT NULL,
            answer JSONB NOT NULL DEFAULT '{}'::jsonb,
            skipped BOOLEAN NOT NULL DEFAULT false,
            source VARCHAR(20) NOT NULL DEFAULT 'manual',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_intake_answer "
        "ON tenant_intake_answers (tenant_id, vertical_key, question_key)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_intake_answer_tenant "
        "ON tenant_intake_answers (tenant_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_intake_answers")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS intake_sub_focus")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS vertical_key")
