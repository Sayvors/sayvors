"""Admin-managed embedding providers, configured apart from the chat ones.

The embedding backend gets its own key, model and base URL. Two reasons:

* the two are bought, rotated and rate-limited separately - many providers
  sell chat without selling embeddings;
* with pgvector the embedding *model* is load-bearing: vectors from
  different models are not comparable, so the model recorded on the config
  decides which stored chunks the vector search may score.

Without an active row the code falls back to the text-generation keys, so an
installation that has not configured embeddings on purpose keeps working
(``rag.embeddings`` logs that it is doing so).
"""
import sqlalchemy as sa
from alembic import op

revision = "f2e3d4c5b6a7"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent: a database that already carries the table (a partial run)
    # must not fail the boot.
    if op.get_bind().dialect.has_table("embedding_provider_configs"):
        return
    op.create_table(
        "embedding_provider_configs",
        sa.Column("provider", sa.String(length=32), primary_key=True),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("key_encrypted", sa.Text(), nullable=True),
        sa.Column("base_url", sa.String(length=200), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("embedding_provider_configs")
