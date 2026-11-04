"""Retire Localith: migrate useful history, drop its schema.

Native Google Business Profile has been the only product path since the
Localith adapter was deleted. This migration removes the remaining traces:

  * daily metrics and posts that belonged to a Localith-mirrored channel are
    re-keyed to the native Google channel for the same Place ID, so history is
    not lost;
  * duplicated Localith reviews/replies and per-channel settings are deleted
    with the mirrored channel row (the native channel already holds the same
    reviews from Google);
  * the ``localith_connections`` table is dropped;
  * ``localith_response`` becomes ``google_response`` on posts/media, which is
    what those columns have stored since the native publisher landed.

The destructive data step is intentionally a one-way migration. A local
backup can be captured before running it; downgrade only restores the empty
schema, never the deleted rows.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "b7e4f1a9c2d8"
down_revision: Union[str, None] = "f5a8c2d6e9b14375"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_COLUMN = "localith_response"
GOOGLE_COLUMN = "google_response"
LEGACY_TABLES = ("location_posts", "location_media")


def _metadata(value) -> dict:
    import json

    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _legacy_channel_ids(bind) -> list[str]:
    """Channel rows created by the Localith mirror, identified by metadata."""
    rows = bind.execute(sa.text("SELECT id, metadata_json FROM channels")).fetchall()
    legacy = []
    for channel_id, raw in rows:
        meta = _metadata(raw)
        if str(meta.get("provider") or "").lower() == "localith" or "listing_id" in meta:
            legacy.append(channel_id)
    return legacy


def _native_target(bind, legacy_id: str) -> dict | None:
    """The native Google channel for the same user + Place ID, if any."""
    row = bind.execute(
        sa.text("SELECT id, user_id, metadata_json FROM channels WHERE id = :id"),
        {"id": legacy_id},
    ).fetchone()
    if row is None:
        return None
    legacy_meta = _metadata(row[2])
    place_id = str(legacy_meta.get("place_id") or legacy_meta.get("location_id") or "")
    if not place_id:
        return None
    candidates = bind.execute(
        sa.text(
            "SELECT id, user_id, metadata_json FROM channels "
            "WHERE user_id = :user_id AND platform = 'google_reviews' AND id != :legacy"
        ),
        {"user_id": row[1], "legacy": legacy_id},
    ).fetchall()
    for candidate in candidates:
        meta = _metadata(candidate[2])
        if str(meta.get("provider") or "").lower() == "localith":
            continue
        if "listing_id" in meta and "location_id" not in meta:
            continue
        if place_id in {
            str(meta.get("place_id") or ""),
            str(meta.get("location_id") or ""),
        }:
            return {
                "id": candidate[0],
                "user_id": candidate[1],
                "listing_id": str(meta.get("location_id") or candidate[0]),
            }
    return None


def _native_channels_for_place(bind, place_id: str) -> list[dict]:
    """Native Google channels (any tenant) matching a Place ID."""
    rows = bind.execute(
        sa.text(
            "SELECT id, user_id, metadata_json FROM channels "
            "WHERE platform = 'google_reviews'"
        )
    ).fetchall()
    out = []
    for channel_id, user_id, raw in rows:
        meta = _metadata(raw)
        if str(meta.get("provider") or "").lower() == "localith":
            continue
        if "listing_id" in meta and "location_id" not in meta:
            continue
        if place_id in {
            str(meta.get("place_id") or ""),
            str(meta.get("location_id") or ""),
        }:
            out.append({
                "id": channel_id,
                "user_id": user_id,
                "listing_id": str(meta.get("location_id") or channel_id),
            })
    return out


def _rekey_profile(
    bind, *, user_id: str, legacy_listing_id: str, target: dict
) -> None:
    """Move a profile to the native listing id unless one already exists."""
    native = bind.execute(
        sa.text(
            "SELECT id FROM location_profiles "
            "WHERE user_id = :user_id AND listing_id IN (:target_listing, :target_id)"
        ),
        {
            "user_id": user_id,
            "target_listing": target["listing_id"],
            "target_id": target["id"],
        },
    ).fetchone()
    legacy = bind.execute(
        sa.text(
            "SELECT id FROM location_profiles "
            "WHERE user_id = :user_id AND listing_id = :legacy_listing"
        ),
        {"user_id": user_id, "legacy_listing": legacy_listing_id},
    ).fetchone()
    if legacy is None:
        return
    if native is not None:
        if native[0] != legacy[0]:
            bind.execute(
                sa.text("DELETE FROM location_profiles WHERE id = :id"),
                {"id": legacy[0]},
            )
        return
    bind.execute(
        sa.text(
            "UPDATE location_profiles SET listing_id = :target_listing WHERE id = :id"
        ),
        {"target_listing": target["listing_id"], "id": legacy[0]},
    )


def _dependent_tables(bind) -> list[str]:
    """Every table with a channel_id column, so no FK blocks the delete."""
    inspector = inspect(bind)
    out = []
    for table in inspector.get_table_names():
        if table == "channels":
            continue
        if any(col["name"] == "channel_id" for col in inspector.get_columns(table)):
            out.append(table)
    return out


def _rename_response_column(bind, table: str) -> None:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns(table)}
    if LEGACY_COLUMN in columns and GOOGLE_COLUMN not in columns:
        op.alter_column(table, LEGACY_COLUMN, new_column_name=GOOGLE_COLUMN)


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Columns keep the Google response under an honest name.
    for table in LEGACY_TABLES:
        _rename_response_column(bind, table)

    # 2. Build the Localith listing -> Place ID map before the table is
    # dropped. It lets a post/profile created under the old listing id find
    # the native channel even when the mirrored channel belonged to another
    # user record for the same business.
    inspector = inspect(bind)
    connection_rows = []
    if "localith_connections" in inspector.get_table_names():
        connection_rows = bind.execute(
            sa.text(
                "SELECT user_id, listing_id, listing_google_id "
                "FROM localith_connections"
            )
        ).fetchall()
    place_by_listing = {
        str(row[1]): str(row[2]) for row in connection_rows if row[2]
    }

    # 2a. Same-tenant history: daily metrics and profiles move to that
    # tenant's native channel for the same Place ID. Cross-tenant metrics are
    # deliberately not moved (they belong to the old tenant record).
    legacy_ids = _legacy_channel_ids(bind)
    for legacy_id in legacy_ids:
        target = _native_target(bind, legacy_id)
        if target is None:
            continue

        legacy = bind.execute(
            sa.text("SELECT listing_key FROM channels WHERE id = :id"),
            {"id": legacy_id},
        ).fetchone()
        legacy_listing_id = str(legacy[0] or "") if legacy else ""

        # Keep every date the native channel does not already have; native
        # wins on overlap.
        bind.execute(
            sa.text(
                "UPDATE location_daily_metrics SET channel_id = :target "
                "WHERE channel_id = :legacy AND date NOT IN ("
                "  SELECT date FROM location_daily_metrics WHERE channel_id = :target"
                ")"
            ),
            {"target": target["id"], "legacy": legacy_id},
        )

        if legacy_listing_id:
            _rekey_profile(
                bind,
                user_id=target["user_id"],
                legacy_listing_id=legacy_listing_id,
                target=target,
            )

    # 2b. Posts/media are owned by the tenant that created them, which can be
    # a different user record from the old Localith connection. Re-key by the
    # listing's Place ID to the native channel owned by the post's tenant.
    for legacy_listing_id, place_id in place_by_listing.items():
        for target in _native_channels_for_place(bind, place_id):
            bind.execute(
                sa.text(
                    "UPDATE location_posts SET listing_id = :target_listing, "
                    "google_response = NULL "
                    "WHERE user_id = :user_id AND listing_id = :legacy_listing"
                ),
                {
                    "target_listing": target["listing_id"],
                    "user_id": target["user_id"],
                    "legacy_listing": legacy_listing_id,
                },
            )
            bind.execute(
                sa.text(
                    "UPDATE location_media SET listing_id = :target_listing, "
                    "google_response = NULL "
                    "WHERE user_id = :user_id AND listing_id = :legacy_listing"
                ),
                {
                    "target_listing": target["listing_id"],
                    "user_id": target["user_id"],
                    "legacy_listing": legacy_listing_id,
                },
            )
            _rekey_profile(
                bind,
                user_id=target["user_id"],
                legacy_listing_id=legacy_listing_id,
                target=target,
            )

    # 3. Remove the mirrored channel and every row that hangs off it.
    if legacy_ids:
        dependent = _dependent_tables(bind)
        for table in dependent:
            bind.execute(
                sa.text(f'DELETE FROM "{table}" WHERE channel_id IN :ids').bindparams(
                    sa.bindparam("ids", expanding=True)
                ),
                {"ids": legacy_ids},
            )
        bind.execute(
            sa.text("DELETE FROM channels WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": legacy_ids},
        )

    # 4. Drop the Localith connection table.
    inspector = inspect(bind)
    if "localith_connections" in inspector.get_table_names():
        op.drop_table("localith_connections")


def downgrade() -> None:
    """Restore the schema only. Deleted Localith rows are not recoverable."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if "localith_connections" not in inspector.get_table_names():
        op.create_table(
            "localith_connections",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("listing_id", sa.String(length=64), nullable=False),
            sa.Column("listing_name", sa.String(length=255), nullable=False),
            sa.Column("listing_google_id", sa.String(length=128), nullable=True),
            sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("api_key_encrypted", sa.Text(), nullable=True),
            sa.Column("address", sa.String(length=500), nullable=True),
            sa.Column("phone_number", sa.String(length=64), nullable=True),
            sa.Column("website_url", sa.String(length=500), nullable=True),
            sa.Column("maps_url", sa.String(length=500), nullable=True),
            sa.Column("store_code", sa.String(length=128), nullable=True),
            sa.Column("is_verified", sa.Boolean(), nullable=True),
            sa.Column("is_disabled", sa.Boolean(), nullable=True),
            sa.Column("is_suspended", sa.Boolean(), nullable=True),
            sa.Column("total_reviews", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("average_rating", sa.Float(), nullable=False, server_default="0"),
            sa.Column("last_review_on", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_reply_on", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_listing_json", sa.JSON(), nullable=True),
            sa.Column("profile_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("raw_metrics_json", sa.JSON(), nullable=True),
            sa.Column("raw_item_metrics_json", sa.JSON(), nullable=True),
            sa.Column("metrics_start", sa.Date(), nullable=True),
            sa.Column("metrics_end", sa.Date(), nullable=True),
            sa.Column("metrics_synced_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "listing_id", name="uq_localith_user_listing"),
        )
        op.create_index(
            "ix_localith_connections_user_id",
            "localith_connections",
            ["user_id"],
        )

    inspector = inspect(bind)
    for table in LEGACY_TABLES:
        if table not in inspector.get_table_names():
            continue
        columns = {col["name"] for col in inspector.get_columns(table)}
        if GOOGLE_COLUMN in columns and LEGACY_COLUMN not in columns:
            op.alter_column(table, GOOGLE_COLUMN, new_column_name=LEGACY_COLUMN)
