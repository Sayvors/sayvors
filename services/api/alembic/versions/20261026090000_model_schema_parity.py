"""Model/migration parity: indexes, foreign keys, defaults and dead columns.

The ORM models are the schema source of truth. This revision closes the
directions of drift the cross-check found:

* ``ReviewIssue.needs_attention`` is declared with ``index=True`` in the
  model, but the index was never migrated. The ticket queue filters on it.
* ``ChannelMessage.platform_message_id`` is a partial unique index in the
  migration (replay dedupe) but the model declared a plain index. The model
  now declares the partial unique index; no database change is needed.
* ``TeamMember.user_id`` is unique in the model (one workspace per user) but
  the migrated database had only a plain index. This revision makes the index
  unique.
* ``ChannelDailyMetric.channel_id`` cascades on channel deletion in the model,
  like the other analytics tables, but the migrated foreign key had no
  ``ON DELETE`` clause. This revision recreates it with ``CASCADE``.
* ``event_outbox`` still carries four columns and three indexes from the
  abandoned meta-events lease design (``worker_id``, ``claimed_at``,
  ``claimed_until``, ``processing_started_at``). Nothing reads or writes
  them; the worker uses ``lease_owner`` / ``lease_expires_at``. Keeping them
  would force the model to describe dead schema.
* ``auto_reply_configs.model`` still carried the original
  ``'openai:gpt-4o-mini'`` server default. The column is nullable and NULL
  means "tenant default, resolved from the admin-managed enabled models";
  the stale default silently filled every insert that omitted the column or
  passed NULL. ``v8w9x0y1z2a3`` reset the stored values but never dropped it.

Everything is written with ``IF EXISTS`` / ``IF NOT EXISTS`` / guarded DO
blocks so re-running the revision on a partially repaired database is safe.

Revision ID: 20261026090000
Revises: z5a6b7c8d9e0
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261026090000"
down_revision: Union[str, None] = "z5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEAD_OUTBOX_INDEXES = (
    "ix_event_outbox_claim",
    "ix_event_outbox_claimed_until",
    "ix_event_outbox_worker_id",
)

_DEAD_OUTBOX_COLUMNS = (
    "processing_started_at",
    "claimed_until",
    "claimed_at",
    "worker_id",
)


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_issues_needs_attention "
        "ON review_issues (needs_attention)"
    )

    # NULL means "resolve the tenant default from the admin-managed enabled
    # models". The original table default predates that design and would fill
    # the column on any insert that omits it, so drop it. Metadata-only and
    # re-runnable.
    op.execute(
        "ALTER TABLE auto_reply_configs ALTER COLUMN model DROP DEFAULT"
    )

    for index_name in _DEAD_OUTBOX_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
    for column_name in _DEAD_OUTBOX_COLUMNS:
        op.execute(
            f"ALTER TABLE event_outbox DROP COLUMN IF EXISTS {column_name}"
        )

    # One workspace per user: the model enforces it with a unique index, the
    # migrated database only had a plain one. No duplicates existed when this
    # revision was written; the unique build fails loudly if that changed.
    op.execute("DROP INDEX IF EXISTS ix_team_members_user_id")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_team_members_user_id "
        "ON team_members (user_id)"
    )

    # The model cascades channel deletion to its daily rollups, like the other
    # analytics tables. The original migration created the FK without ON
    # DELETE, so deleting a channel with rollups raised a foreign-key error.
    # The DO block is re-runnable: it only touches a non-cascading constraint
    # and only adds the constraint when it is absent.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'channel_daily_metrics'::regclass
                  AND conname = 'channel_daily_metrics_channel_id_fkey'
                  AND confdeltype <> 'c'
            ) THEN
                ALTER TABLE channel_daily_metrics
                    DROP CONSTRAINT channel_daily_metrics_channel_id_fkey;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'channel_daily_metrics'::regclass
                  AND conname = 'channel_daily_metrics_channel_id_fkey'
            ) THEN
                ALTER TABLE channel_daily_metrics
                    ADD CONSTRAINT channel_daily_metrics_channel_id_fkey
                    FOREIGN KEY (channel_id) REFERENCES channels(id)
                    ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE auto_reply_configs ALTER COLUMN model "
        "SET DEFAULT 'openai:gpt-4o-mini'"
    )
    op.execute(
        "ALTER TABLE event_outbox ADD COLUMN IF NOT EXISTS "
        "worker_id VARCHAR(128)"
    )
    op.execute(
        "ALTER TABLE event_outbox ADD COLUMN IF NOT EXISTS "
        "claimed_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE event_outbox ADD COLUMN IF NOT EXISTS "
        "claimed_until TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE event_outbox ADD COLUMN IF NOT EXISTS "
        "processing_started_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_event_outbox_claim "
        "ON event_outbox (status, next_retry_at, claimed_until)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_event_outbox_claimed_until "
        "ON event_outbox (claimed_until)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_event_outbox_worker_id "
        "ON event_outbox (worker_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_review_issues_needs_attention")

    op.execute("DROP INDEX IF EXISTS ix_team_members_user_id")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_team_members_user_id "
        "ON team_members (user_id)"
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'channel_daily_metrics'::regclass
                  AND conname = 'channel_daily_metrics_channel_id_fkey'
                  AND confdeltype = 'c'
            ) THEN
                ALTER TABLE channel_daily_metrics
                    DROP CONSTRAINT channel_daily_metrics_channel_id_fkey;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conrelid = 'channel_daily_metrics'::regclass
                  AND conname = 'channel_daily_metrics_channel_id_fkey'
            ) THEN
                ALTER TABLE channel_daily_metrics
                    ADD CONSTRAINT channel_daily_metrics_channel_id_fkey
                    FOREIGN KEY (channel_id) REFERENCES channels(id);
            END IF;
        END $$;
        """
    )
