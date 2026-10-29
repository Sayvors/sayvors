"""profile_images

Revision ID: d6e7f8a9b0c1
Revises: h4b5c6d7e8f9
Create Date: 2026-10-29 10:00:00.000000

Add the per-source avatar columns and the cover image to users.

`avatar_url` stays the single effective URL every consumer renders. The new
columns only record where that URL came from, so the profile page can offer a
Google / Facebook / device switch without another provider round-trip, and a
device upload is not silently replaced by the next Google sign-in.

Existing rows are backfilled from `avatar_url`: the account was signed in with
Google or Facebook when that URL was captured, so it belongs to that source.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "h4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS keeps a re-run safe: a deploy that crashed between the
    # DDL and alembic's version bump must be able to run this again.
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_source VARCHAR(16)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS google_avatar_url VARCHAR(1000)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS facebook_avatar_url VARCHAR(1000)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_upload_url VARCHAR(1000)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_storage_key VARCHAR(500)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cover_url VARCHAR(1000)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS cover_storage_key VARCHAR(500)")

    # Provider picture URLs (Facebook lookaside especially) can exceed the old
    # 500-char column, and a truncated URL is a silently broken avatar.
    op.execute("ALTER TABLE users ALTER COLUMN avatar_url TYPE VARCHAR(1000)")

    # Backfill the provider snapshot. A row with both identities cannot tell
    # which provider produced the last picture; Google wins deterministically
    # so the value is stable, and the user can switch with one click.
    op.execute(
        """
        UPDATE users
        SET google_avatar_url = avatar_url
        WHERE avatar_url IS NOT NULL
          AND google_sub IS NOT NULL
          AND google_avatar_url IS NULL
        """
    )
    op.execute(
        """
        UPDATE users
        SET facebook_avatar_url = avatar_url
        WHERE avatar_url IS NOT NULL
          AND facebook_id IS NOT NULL
          AND facebook_avatar_url IS NULL
        """
    )
    op.execute(
        """
        UPDATE users
        SET avatar_source = CASE
            WHEN google_avatar_url IS NOT NULL THEN 'google'
            WHEN facebook_avatar_url IS NOT NULL THEN 'facebook'
            ELSE NULL
        END
        WHERE avatar_source IS NULL AND avatar_url IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS cover_storage_key")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS cover_url")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS avatar_storage_key")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS avatar_upload_url")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS facebook_avatar_url")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS google_avatar_url")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS avatar_source")
