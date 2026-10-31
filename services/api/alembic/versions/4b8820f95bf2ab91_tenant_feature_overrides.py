"""tenant_subscriptions.features_override

Per-tenant feature overrides. A plan defines the baseline feature set; an
override dict on the subscription wins per key, so one tenant can have a
feature the plan lacks (or lose one the plan includes) without forking the
plan for everybody. An empty dict means "inherit the plan exactly" — that is
also what the Special list keys off.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '4b8820f95bf2ab91'
down_revision: Union[str, None] = 'f2ff03638689'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_subscriptions",
        sa.Column(
            "features_override",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_subscriptions", "features_override")
