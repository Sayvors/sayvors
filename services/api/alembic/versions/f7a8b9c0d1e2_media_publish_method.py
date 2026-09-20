"""location_media.publish_method: how the photo reaches Google.

post = inside a Google post (wired via Localith). gallery / profile are
stored intent until per-tenant native Google lands — the API rejects
publishing anything but post until then.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "location_media",
        sa.Column("publish_method", sa.String(16), nullable=False, server_default="post"),
    )


def downgrade() -> None:
    op.drop_column("location_media", "publish_method")
