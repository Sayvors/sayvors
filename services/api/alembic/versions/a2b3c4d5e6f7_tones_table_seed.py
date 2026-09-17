"""tones table + seed of the 4 response tones.

The catalog lives in the DB from here on (admin-managed via
POST/DELETE /api/v1/admin/tones).

Revision ID: a2b3c4d5e6f7
Revises: z1a2b3c4d5e6
Create Date: 2026-09-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "z1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED: list[tuple[str, str, str]] = [
    ("friendly", "Friendly", "warm and casual"),
    ("professional", "Professional", "formal and polished"),
    ("apologetic", "Apologetic", "extra empathetic"),
    ("playful", "Playful", "light and fun"),
]


def upgrade() -> None:
    op.create_table(
        "tones",
        sa.Column("code", sa.String(30), primary_key=True),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    tones_table = sa.table(
        "tones",
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("description", sa.String),
    )
    existing = {row[0] for row in op.get_bind().execute(sa.text("SELECT code FROM tones"))}
    op.bulk_insert(
        tones_table,
        [
            {"code": code, "label": label, "description": desc}
            for code, label, desc in SEED
            if code not in existing
        ],
    )


def downgrade() -> None:
    op.drop_table("tones")
