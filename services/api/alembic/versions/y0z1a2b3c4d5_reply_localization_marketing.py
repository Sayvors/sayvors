"""reply localization + marketing prefs + account country.

AutoReplyConfig gains dialect (catalog code or 'auto'), reply_language
policy (match/en/ar), and four promotional toggles (all default OFF =
today's behavior). users gains a single account-wide country code.

Revision ID: y0z1a2b3c4d5
Revises: x9y0z1a2b3c4
Create Date: 2026-09-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "y0z1a2b3c4d5"
down_revision: Union[str, None] = "x9y0z1a2b3c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auto_reply_configs",
        sa.Column("dialect", sa.String(30), nullable=False, server_default="auto"),
    )
    op.add_column(
        "auto_reply_configs",
        sa.Column("reply_language", sa.String(10), nullable=False, server_default="match"),
    )
    op.add_column(
        "auto_reply_configs",
        sa.Column("promo_product_mentions", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "auto_reply_configs",
        sa.Column("promo_links", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "auto_reply_configs",
        sa.Column("promo_only_relevant", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "auto_reply_configs",
        sa.Column("promo_max_ctas", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "users",
        sa.Column("country", sa.String(8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "country")
    op.drop_column("auto_reply_configs", "promo_max_ctas")
    op.drop_column("auto_reply_configs", "promo_only_relevant")
    op.drop_column("auto_reply_configs", "promo_links")
    op.drop_column("auto_reply_configs", "promo_product_mentions")
    op.drop_column("auto_reply_configs", "reply_language")
    op.drop_column("auto_reply_configs", "dialect")
