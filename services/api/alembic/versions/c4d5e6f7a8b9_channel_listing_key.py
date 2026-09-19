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


# Child tables holding channel_id. Plain tables re-point blindly; the three
# tables below carry their own unique constraints, so colliding rows are
# resolved first (survivor wins, dupe fills its gaps, dupe rows go).
_PLAIN_CHILD_TABLES: tuple[str, ...] = (
    "channel_messages",
    "review_replies",
    "channel_services",
    "llm_usage_events",
    "review_response_logs",
)

# Single-row-per-channel tables: keep the survivor's row when it has one,
# otherwise the dupe's row moves over.
_UNIQUE_CHILD_TABLES: tuple[str, ...] = (
    "auto_reply_configs",
    "channel_verifications",
)


def _tables_present(bind) -> set[str]:
    from sqlalchemy import inspect as _inspect

    try:
        return set(_inspect(bind).get_table_names())
    except Exception:
        return set()


def _merge_insights(bind, survivor: str, dupe: str) -> None:
    """Fold the dupe's reviews into the survivor's.

    Both twins synced the same reviews, so most review_ids collide under
    uq_review_insights_channel_review. The survivor keeps its row; gaps
    (unfetched text, missing reply flags, pending enrichment) are filled
    from the dupe before its colliding rows are dropped.
    """
    bind.execute(
        sa.text(
            # NOTE: target table written WITHOUT alias — SQLite (tests)
            # rejects aliased UPDATE targets; Postgres accepts both.
            """
            UPDATE review_insights SET
              review_text = COALESCE(NULLIF(review_insights.review_text, ''), d.review_text),
              reviewer_name = COALESCE(NULLIF(review_insights.reviewer_name, ''), d.reviewer_name),
              review_url = COALESCE(NULLIF(review_insights.review_url, ''), d.review_url),
              replied = review_insights.replied OR d.replied,
              replied_at = COALESCE(review_insights.replied_at, d.replied_at),
              skipped = review_insights.skipped OR d.skipped,
              edited = review_insights.edited OR d.edited,
              edited_at = COALESCE(review_insights.edited_at, d.edited_at),
              previous_review_text = COALESCE(review_insights.previous_review_text, d.previous_review_text),
              previous_rating = COALESCE(review_insights.previous_rating, d.previous_rating),
              sentiment = CASE WHEN review_insights.enrichment_status = 'pending'
                                 AND d.enrichment_status = 'done'
                               THEN d.sentiment ELSE review_insights.sentiment END,
              sentiment_score = CASE WHEN review_insights.enrichment_status = 'pending'
                                       AND d.enrichment_status = 'done'
                                     THEN d.sentiment_score ELSE review_insights.sentiment_score END,
              topics = CASE WHEN review_insights.enrichment_status = 'pending'
                              AND d.enrichment_status = 'done'
                            THEN d.topics ELSE review_insights.topics END,
              products = CASE WHEN review_insights.enrichment_status = 'pending'
                                AND d.enrichment_status = 'done'
                              THEN d.products ELSE review_insights.products END,
              problems = CASE WHEN review_insights.enrichment_status = 'pending'
                                AND d.enrichment_status = 'done'
                              THEN d.problems ELSE review_insights.problems END,
              enrichment_status = CASE WHEN review_insights.enrichment_status = 'pending'
                                         AND d.enrichment_status = 'done'
                                       THEN d.enrichment_status ELSE review_insights.enrichment_status END
            FROM review_insights d
            WHERE d.channel_id = :dupe
              AND review_insights.channel_id = :surv
              AND review_insights.review_id = d.review_id
            """
        ),
        {"dupe": dupe, "surv": survivor},
    )
    bind.execute(
        sa.text(
            "DELETE FROM review_insights WHERE channel_id = :dupe "
            "AND review_id IN "
            "(SELECT review_id FROM review_insights WHERE channel_id = :surv)"
        ),
        {"dupe": dupe, "surv": survivor},
    )
    bind.execute(
        sa.text("UPDATE review_insights SET channel_id = :surv WHERE channel_id = :dupe"),
        {"dupe": dupe, "surv": survivor},
    )


def _merge_duplicate_channels(bind) -> int:
    """Merge twin channels per (user_id, platform, listing_key).

    Returns the number of deleted rows. Keeps the oldest row per key.
    Collision-safe on every unique constraint in the schema that references
    channel_id (insights, daily metrics, intel reports, per-channel single
    rows) — the merge, not the constraint creation, is where twins die.
    """
    present = _tables_present(bind)
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
            if "review_insights" in present:
                _merge_insights(bind, survivor, dupe)
            if "location_daily_metrics" in present:
                # Same day synced into both twins: survivor's day wins
                # (metrics rebuild from insights anyway).
                bind.execute(
                    sa.text(
                        "DELETE FROM location_daily_metrics WHERE channel_id = :dupe "
                        "AND date IN "
                        "(SELECT date FROM location_daily_metrics WHERE channel_id = :surv)"
                    ),
                    {"dupe": dupe, "surv": survivor},
                )
                bind.execute(
                    sa.text(
                        "UPDATE location_daily_metrics SET channel_id = :surv "
                        "WHERE channel_id = :dupe"
                    ),
                    {"dupe": dupe, "surv": survivor},
                )
            if "review_intelligence_reports" in present:
                # Regenerable reports: survivor's scope wins on conflict.
                bind.execute(
                    sa.text(
                        "DELETE FROM review_intelligence_reports WHERE channel_id = :dupe "
                        "AND (user_id, days) IN "
                        "(SELECT user_id, days FROM review_intelligence_reports "
                        "WHERE channel_id = :surv)"
                    ),
                    {"dupe": dupe, "surv": survivor},
                )
                bind.execute(
                    sa.text(
                        "UPDATE review_intelligence_reports SET channel_id = :surv "
                        "WHERE channel_id = :dupe"
                    ),
                    {"dupe": dupe, "surv": survivor},
                )
            for table in _PLAIN_CHILD_TABLES:
                if table not in present:
                    continue
                bind.execute(
                    sa.text(f"UPDATE {table} SET channel_id = :s WHERE channel_id = :d"),
                    {"s": survivor, "d": dupe},
                )
            for table in _UNIQUE_CHILD_TABLES:
                if table not in present:
                    continue
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
