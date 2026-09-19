"""channels.listing_key + one-row-per-location guarantee.

Each google_reviews channel gets a stable location identity (Localith
listing_id, or Google location_id for native OAuth rows). A unique
constraint on (user_id, platform, listing_key) makes twin rows physically
impossible however many uvicorn workers race — losers reuse the winner's
row (get-or-create in channels/localith code).

The upgrade backfills the key from metadata_json, MERGES any twin rows
created by the old check-then-insert race (keeps the oldest per key,
re-points every child table, deletes the extras), and only then creates
the constraint — so deploy never fails on existing staging data.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-19 00:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _listing_key(platform: str | None, metadata_json: str | None) -> str | None:
    if platform != "google_reviews" or not metadata_json:
        return None
    try:
        meta = json.loads(metadata_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    key = meta.get("listing_id") or meta.get("location_id")
    return str(key) if key else None


# (child_table, unique_per_channel): unique tables keep the survivor's own
# row when it has one, otherwise the dupe's row moves over.
_CHILD_TABLES: tuple[tuple[str, bool], ...] = (
    ("channel_messages", False),
    ("review_replies", False),
    ("review_insights", False),
    ("channel_services", False),
    ("auto_reply_configs", True),
    ("channel_verifications", True),
)


def _merge_duplicate_channels(bind) -> int:
    """Merge twin channels per (user_id, platform, listing_key).

    Returns the number of deleted rows. Keeps the oldest row per key.
    """
    rows = bind.execute(
        sa.text(
            "SELECT id, user_id, platform, listing_key FROM channels "
            "WHERE listing_key IS NOT NULL "
            "ORDER BY user_id, platform, listing_key, created_at, id"
        )
    ).all()
    groups: dict[tuple[str, str, str], list[str]] = {}
    for row in rows:
        groups.setdefault((row.user_id, row.platform, row.listing_key), []).append(row.id)
    deleted = 0
    for (_user_id, _platform, _key), ids in groups.items():
        if len(ids) < 2:
            continue
        survivor, dupes = ids[0], ids[1:]
        for dupe in dupes:
            for table, unique_per_channel in _CHILD_TABLES:
                if unique_per_channel:
                    has_own = bind.execute(
                        sa.text(f"SELECT 1 FROM {table} WHERE channel_id = :s LIMIT 1"),
                        {"s": survivor},
                    ).first()
                    if has_own:
                        bind.execute(
                            sa.text(f"DELETE FROM {table} WHERE channel_id = :d"),
                            {"d": dupe},
                        )
                        continue
                bind.execute(
                    sa.text(f"UPDATE {table} SET channel_id = :s WHERE channel_id = :d"),
                    {"s": survivor, "d": dupe},
                )
            bind.execute(sa.text("DELETE FROM channels WHERE id = :d"), {"d": dupe})
            deleted += 1
    return deleted


def upgrade() -> None:
    op.add_column("channels", sa.Column("listing_key", sa.String(128), nullable=True))
    op.create_index("ix_channels_listing_key", "channels", ["listing_key"])

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, platform, metadata_json FROM channels")).all()
    for row in rows:
        key = _listing_key(row.platform, row.metadata_json)
        if key:
            bind.execute(
                sa.text("UPDATE channels SET listing_key = :k WHERE id = :i"),
                {"k": key, "i": row.id},
            )

    merged = _merge_duplicate_channels(bind)
    # Visible in deploy logs: proves the twin cleanup ran.
    print(f"channels.listing_key backfill done, merged {merged} duplicate channel row(s)")

    op.create_unique_constraint(
        "uq_channels_user_platform_key", "channels", ["user_id", "platform", "listing_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_channels_user_platform_key", "channels", type_="unique")
    op.drop_index("ix_channels_listing_key", table_name="channels")
    op.drop_column("channels", "listing_key")
