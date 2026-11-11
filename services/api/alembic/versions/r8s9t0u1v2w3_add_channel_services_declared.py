"""Add channel_services.declared — the merchant's choice, not the catalogue.

Google's category service types are a catalogue: every "Software company"
could offer "Data center management", but Google does not list it for a
business until the merchant declares it. The Services page showed all of
them as the business's own services, and the AI quoted them as ground truth.

`declared` records the merchant's choice. Undeclared rows stay suggestions;
declared rows are published to Google as serviceItems and are the only ones
the AI may quote. Existing rows default to false, which matches what Google
actually holds: a location's serviceItems list is empty until the merchant
declares a service.

Revision ID: r8s9t0u1v2w3
Revises: q7w8e9r0t1y2
Create Date: 2026-11-10
"""
from typing import Sequence, Union

from alembic import op

revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, None] = "q7w8e9r0t1y2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS keeps the migration re-runnable on a database that
    # already has the column (a partially applied deploy).
    op.execute(
        "ALTER TABLE channel_services "
        "ADD COLUMN IF NOT EXISTS declared BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE channel_services DROP COLUMN IF EXISTS declared"
    )
