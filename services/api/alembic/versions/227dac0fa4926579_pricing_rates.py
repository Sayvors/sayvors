"""pricing_rates

The admin-editable billable rate card: LLM input/output cents per 1M tokens
per provider family, ASR cents per audio minute, TTS cents per 1k characters.

Additive: the table starts empty, and ``billing.pricing`` falls back to the
code defaults (the pre-existing LLM pass-through table and 0 for voice), so
prices do not change until an operator edits a rate.

Revision ID: 227dac0fa4926579
Revises: ed44c60beb4c92aa
"""

from typing import Sequence, Union

from alembic import op

revision: str = "227dac0fa4926579"
down_revision: Union[str, None] = "ed44c60beb4c92aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pricing_rates (
            kind VARCHAR(24) NOT NULL,
            key VARCHAR(64) NOT NULL,
            unit_price_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (kind, key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pricing_rates")
