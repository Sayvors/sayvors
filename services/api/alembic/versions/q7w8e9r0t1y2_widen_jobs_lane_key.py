"""Widen jobs.lane_key for composite partition keys.

The publish router builds lane_key as
f"{tenant_id}:{platform}:{asset_id}:{method}". A tenant UUID plus a Google
location id plus the method easily exceeds the original VARCHAR(64), so
publishing a banner failed with "value too long for type character
varying(64)". The key is a Kafka partition key / lane admission handle, not
a unique constraint, so it is kept intact rather than truncated.

Revision ID: q7w8e9r0t1y2
Revises: ff6a7b8c9d0e
Create Date: 2026-11-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = "q7w8e9r0t1y2"
down_revision: Union[str, None] = "ff6a7b8c9d0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ALTER COLUMN lane_key TYPE VARCHAR(200)")


def downgrade() -> None:
    # Narrowing is only safe after long keys are gone; LEFT makes the
    # truncation explicit rather than failing on every existing row.
    op.execute(
        "ALTER TABLE jobs ALTER COLUMN lane_key TYPE VARCHAR(64) "
        "USING LEFT(lane_key, 64)"
    )
