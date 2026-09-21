"""Reply model becomes tenant-default (nullable, no hardcoded Groq default).

Revision ID: v8w9x0y1z2a3
Revises: u7v8w9x0y1z2
Create Date: 2026-09-21

auto_reply_configs.model was defaulting every new channel to the hardcoded
"groq:openai/gpt-oss-120b". NULL now means "tenant default" resolved from
the admin-managed enabled models at generation time. Existing rows carrying
the legacy hardcoded default are reset to NULL; explicit tenant choices of
any other model are untouched.
"""
import sqlalchemy as sa

from alembic import op

revision = "v8w9x0y1z2a3"
down_revision = "u7v8w9x0y1z2"
branch_labels = None
depends_on = None

_LEGACY_DEFAULT = "groq:openai/gpt-oss-120b"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE auto_reply_configs SET model = NULL "
            "WHERE model = :legacy"
        ).bindparams(legacy=_LEGACY_DEFAULT)
    )
    op.alter_column("auto_reply_configs", "model",
                    existing_type=sa.String(100),
                    nullable=True)


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE auto_reply_configs SET model = :legacy "
            "WHERE model IS NULL"
        ).bindparams(legacy=_LEGACY_DEFAULT)
    )
    op.alter_column("auto_reply_configs", "model",
                    existing_type=sa.String(100),
                    nullable=False)
