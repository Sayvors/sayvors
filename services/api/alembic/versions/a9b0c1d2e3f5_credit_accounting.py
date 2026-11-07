"""Sayvors Credits accounting columns on LLM usage events.

One row per billable call now carries the exact economics, in integers:
provider tokens, attributable infrastructure, delivery cost, retail charge,
credits and the rate-card version. No float is persisted, so a margin audit
can be replayed years later.

Revision ID: a9b0c1d2e3f5
Revises: f9a1b2c3d4e5
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a9b0c1d2e3f5"
down_revision: Union[str, None] = "f9a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("provider_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
    ("infrastructure_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
    ("delivery_cost_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
    ("charge_micro_usd", "BIGINT NOT NULL DEFAULT 0"),
    ("credits_micro", "BIGINT NOT NULL DEFAULT 0"),
    ("margin_bp", "INTEGER NOT NULL DEFAULT 0"),
    ("sc_per_usd", "INTEGER NOT NULL DEFAULT 0"),
    ("pricing_version", "VARCHAR(16) NOT NULL DEFAULT 'v1.0'"),
)


def upgrade() -> None:
    for name, ddl in _COLUMNS:
        op.execute(
            f"ALTER TABLE llm_usage_events ADD COLUMN IF NOT EXISTS {name} {ddl}"
        )


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE llm_usage_events DROP COLUMN IF EXISTS {name}")
