"""Platform-wide AI config: the banner/promotion vision model.

Revision ID: 20261119150000
Revises: 20261119140000
Create Date: 2026-11-19

The admin chooses the vision model used for the banner/promotion photo check.
It is stored in a single-row table (not env) so it can change without a
restart, and it is never returned to tenants — merchants see only the verdict.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261119150000"
down_revision: Union[str, None] = "20261119140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_config (
            id VARCHAR(16) PRIMARY KEY,
            banner_vision_model TEXT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "INSERT INTO platform_config (id) VALUES ('default') ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS platform_config")
