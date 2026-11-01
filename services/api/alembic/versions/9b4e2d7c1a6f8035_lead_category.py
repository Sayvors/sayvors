"""lead_category

Canonical lead labels: wholesale | retail | booking | quote | support | info.

`intent` (buying/booking/quote/info) could not express wholesale, so the only
segment a B2B customer cared about had no home and every surface invented its
own label. This adds one stored category that the engine classifies once and
the inbox, lead card, digest and escalation email render verbatim.

Backfill is deliberately conservative: an existing `intent` maps to the
closest category, and nothing else is guessed. A historical "buying" lead
becomes retail because no volume data exists to prove wholesale; new rows are
classified from the conversation itself.

Revision ID: 9b4e2d7c1a6f8035
Revises: 13d74ad0046228f3
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9b4e2d7c1a6f8035"
down_revision: Union[str, None] = "13d74ad0046228f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CATEGORY = sa.Enum(
    "wholesale",
    "retail",
    "booking",
    "quote",
    "support",
    "info",
    name="lead_category",
)


def upgrade() -> None:
    bind = op.get_bind()
    # checkfirst makes a replayed/partially-applied migration safe: the type
    # is created once even if a previous run got that far before failing.
    _CATEGORY.create(bind, checkfirst=True)
    op.add_column(
        "leads",
        sa.Column("category", _CATEGORY, nullable=True),
    )
    op.create_index(
        "ix_leads_tenant_category",
        "leads",
        ["tenant_id", "category", "created_at"],
        unique=False,
    )

    # Backfill from the old intent. Values are cast explicitly: on Postgres the
    # column is an enum, and a bare string literal would need an implicit cast.
    op.execute(
        """
        UPDATE leads SET category = CASE intent
            WHEN 'buying' THEN 'retail'::lead_category
            WHEN 'booking' THEN 'booking'::lead_category
            WHEN 'quote' THEN 'quote'::lead_category
            WHEN 'info' THEN 'info'::lead_category
            ELSE NULL
        END
        WHERE category IS NULL
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_leads_tenant_category", table_name="leads")
    op.drop_column("leads", "category")
    _CATEGORY.drop(bind, checkfirst=True)
