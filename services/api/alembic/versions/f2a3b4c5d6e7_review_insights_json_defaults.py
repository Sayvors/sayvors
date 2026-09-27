"""Give review_insights' JSON list columns a server default and repair NULLs.

`default=list` in the model is a *Python-side* default: it only applies when
that SQLAlchemy version builds the INSERT. A writer that omits the column
leaves NULL, and a NULL in a `list` field fails validation — so one such row
made `GET /api/v1/analytics/reviews/insights` return 500 for the whole tenant.
That reads as "the reviews page is broken", not "one field is empty".

This happened for real: a server process still running pre-abuse code inserted
rows without `abuse_labels`, and because the column had no server default they
landed as NULL. The offending rows are repaired here, but the hole stays open
for any other writer that omits a column, so the columns also get a real
database-level default.

Forward-only: the earlier revisions are already applied.
"""
import sqlalchemy as sa
from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"

_COLUMNS = ("topics", "products", "problems", "media", "abuse_labels")


def upgrade() -> None:
    # Repair first, so the endpoint stops 500ing even before the DDL lands.
    for col in _COLUMNS:
        op.execute(f"UPDATE review_insights SET {col} = '[]'::json WHERE {col} IS NULL")
    for col in _COLUMNS:
        op.alter_column(
            "review_insights",
            col,
            existing_type=sa.JSON(),
            existing_nullable=True,
            server_default=sa.text("'[]'"),
        )


def downgrade() -> None:
    for col in _COLUMNS:
        op.alter_column(
            "review_insights",
            col,
            existing_type=sa.JSON(),
            existing_nullable=True,
            server_default=None,
        )
