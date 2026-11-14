"""align plan feature flags with real, implemented features

Revision ID: 20261114170000
Revises: 20261114160000
Create Date: 2026-11-14

§34 cleanup: the feature catalog contained entries with no product behind them
(SLA, priority support, AI search, ASK Sayvors premium). They are removed from
the catalog, and this migration deletes the stale keys from every plan's
features JSONB so the admin tenant modal and the tenant plans page only ever
show real, controllable features.

It also fills in the real feature flags each tier should have (from the §6b
recommended catalog), ADDING keys only when absent — an admin's explicit edit
is never overwritten, and no plan is silently downgraded. Enterprise gets the
full set of implemented features (the seed only carried 10 of 21).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261114170000"
down_revision: Union[str, None] = "20261114160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Catalog keys with no product behind them.
_PHANTOM_KEYS = ("sla", "priority_support", "ai_search", "ask_sayvors_premium")

# Real feature flags per tier (added only when absent).
_STARTER = {
    "scheduling", "verifications", "databank",
}
_PRO = _STARTER | {
    "analytics", "automation", "leads", "voice", "assistant",
    "social_response_style", "bulk_edit_csv", "benchmarking",
    "benchmark_external", "growth", "ticket_assignment",
}
_GROWTH = _PRO | {"voice_replies"}
_ENTERPRISE = _GROWTH | {"channels", "messaging", "ai_replies", "posts", "media", "reviews"}


def _drop_phantoms() -> None:
    keys = ", ".join(repr(k) for k in _PHANTOM_KEYS)
    drops = " - ".join(f"'{k}'" for k in _PHANTOM_KEYS)
    op.execute(
        f"UPDATE plans SET features = features - {drops} "
        f"WHERE features ?| ARRAY[{keys}]"
    )


def _add_keys(slug: str, keys: set[str]) -> None:
    for key in sorted(keys):
        op.execute(
            f"UPDATE plans SET features = COALESCE(features, '{{}}'::jsonb) || '{{\"{key}\": true}}'::jsonb "
            f"WHERE slug = '{slug}' AND NOT (COALESCE(features, '{{}}'::jsonb) ? '{key}')"
        )


def upgrade() -> None:
    _drop_phantoms()
    _add_keys("starter", _STARTER)
    _add_keys("pro", _PRO)
    _add_keys("growth", _GROWTH)
    _add_keys("enterprise", _ENTERPRISE)


def downgrade() -> None:
    # Removing flags would downgrade plans; the phantom keys are gone from the
    # catalog anyway, so this migration is intentionally not reversible.
    pass
