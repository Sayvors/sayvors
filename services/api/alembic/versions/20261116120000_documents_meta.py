"""documents.meta: structured extraction payload (§31 Phase B)

Revision ID: 20261116120000
Revises: 20261116090000
Create Date: 2026-11-16

Adds ``documents.meta`` (JSON): the structured document summary produced by
``rag.document_structure.build_structured_doc`` — title/lang, intent,
extractive summary, heading outline, bounded entities (emails/phones/prices).
Nullable: uploads and legacy rows stay valid without it. Idempotent DDL.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261116120000"
down_revision: Union[str, None] = "20261116090000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS meta JSON")


def downgrade() -> None:
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS meta")
