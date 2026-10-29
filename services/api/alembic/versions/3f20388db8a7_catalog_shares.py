"""catalog_shares

The public catalog page is reachable without a session, so the link itself is
the credential: 32 random characters, one row per tenant, revoked by deleting
the row. Deliberately not a column on ``users`` — the catalog must not depend
on the auth model, and the tenant id is not always a user row.

Revision ID: 3f20388db8a7
Revises: 1d8652000947
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "3f20388db8a7"
down_revision = "1d8652000947"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_shares",
        sa.Column("tenant_id", sa.String(36), primary_key=True),
        sa.Column("token", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_catalog_shares_token "
        "ON catalog_shares (token)"
    )


def downgrade() -> None:
    op.drop_table("catalog_shares")
