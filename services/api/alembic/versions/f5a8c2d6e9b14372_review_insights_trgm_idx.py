"""Add pg_trgm extension + GIN trigram indexes on review_insights.

M-9(d): review-insights search filters review_text and reviewer_name with
LOWER(coalesce(col, '')). LIKE '%search%' which a B-tree index cannot serve
because of the leading wildcard. A GIN trigram index makes ILIKE/LIKE with
leading wildcards indexable.

Requires the ``pg_trgm`` PostgreSQL extension. AWS RDS supports it on
supported engine versions; the migration fails loudly rather than silently
degrading to a sequential scan.

Both indexes are built CONCURRENTLY so the write path stays open on a large
table; that requires the autocommit block. All statements are IF NOT EXISTS so
the migration is re-runnable after a partial failure.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "f5a8c2d6e9b14372"
down_revision = "f5a8c2d6e9b14371"
branch_labels = None
depends_on = None

_EXTENSION = "pg_trgm"
_TEXT_INDEX = "ix_review_insights_review_text_trgm"
_NAME_INDEX = "ix_review_insights_reviewer_name_trgm"


def upgrade() -> None:
    try:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {_EXTENSION}")
    except Exception as e:  # noqa: BLE001 - fail loudly with context
        raise RuntimeError(
            "pg_trgm extension is not available on this database, so the "
            "review-insights search indexes cannot be created. Install the "
            "extension and re-run `alembic upgrade head`:\n"
            "  - AWS RDS: the engine version must support pg_trgm, then run "
            "`CREATE EXTENSION IF NOT EXISTS pg_trgm;` as an admin\n"
            "  - Docker/Compose: use a PostgreSQL image with pg_trgm bundled "
            "or install it into the image\n"
            "  - Self-hosted: install the postgresql-contrib package, then "
            "run the CREATE EXTENSION above\n"
            "See docs/database/migration-safety.md for extension policy."
        ) from e

    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_TEXT_INDEX} "
            f"ON review_insights USING gin (review_text gin_trgm_ops)"
        )
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_NAME_INDEX} "
            f"ON review_insights USING gin (reviewer_name gin_trgm_ops)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_TEXT_INDEX}")
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_NAME_INDEX}")
    # The extension is left installed: other objects may depend on it.
