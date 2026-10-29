"""catalog_items

The assistant could describe the business from its profile card but never
quote an item, a price or availability. One tenant-scoped table holds what the
prompt block quotes verbatim.

Revision ID: 1d8652000947
Revises: fbd90ec030b0
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "1d8652000947"
down_revision = "fbd90ec030b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sku", sa.String(80), nullable=True),
        # Numeric, not float: money in a quote must not drift.
        sa.Column("price", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("image_url", sa.String(1000), nullable=True),
        sa.Column("item_url", sa.String(1000), nullable=True),
        sa.Column(
            "in_stock", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column("availability_note", sa.String(200), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default="true"
        ),
        sa.Column(
            "sort_order", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_catalog_items_tenant_id "
        "ON catalog_items (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_catalog_items_tenant_active "
        "ON catalog_items (tenant_id, active, sort_order)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_catalog_items_tenant_sku "
        "ON catalog_items (tenant_id, sku)"
    )


def downgrade() -> None:
    op.drop_table("catalog_items")
