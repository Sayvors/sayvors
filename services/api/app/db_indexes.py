"""PostgreSQL-only DDL that the ORM models cannot express portably.

The models are the schema source of truth: rebuilding the database from
``Base.metadata`` must produce the same objects the Alembic chain creates.
GIN, HNSW, partial and expression indexes have no portable SQLAlchemy form
(SQLite rejects them), so each one is attached to its table as an
``after_create`` hook that runs only on PostgreSQL.

The hooks are no-ops on SQLite, which is what the test suite uses. They only
fire when ``create_all`` actually creates the table, so they never run against
an existing migrated database.

The index names are registered so Alembic autogenerate can skip them: they are
created outside the metadata, and without the filter a routine
``alembic revision --autogenerate`` would propose dropping them.
"""
from collections.abc import Callable

from sqlalchemy import event, text
from sqlalchemy.schema import Table

_MANAGED_INDEX_NAMES: set[str] = set()


def register_postgres_index_ddl(
    table: Table,
    statements: list[str] | Callable[[], list[str]],
    *,
    names: list[str],
) -> None:
    """Create ``statements`` after ``table`` is created on PostgreSQL.

    ``statements`` must be idempotent (``CREATE INDEX IF NOT EXISTS``): a
    rebuild may run them more than once if a previous attempt stopped between
    the table and its indexes. A callable is resolved when the table is
    created, so a statement can depend on runtime settings (for example the
    pgvector HNSW index only exists when embeddings are enabled).

    ``names`` lists the index names the statements create. They are exposed
    through :func:`managed_postgres_index_names` so autogenerate does not
    treat the database-only indexes as objects to drop.
    """
    _MANAGED_INDEX_NAMES.update(names)

    @event.listens_for(table, "after_create")
    def _create_postgres_indexes(target, connection, **kw):  # noqa: ANN001
        if connection.dialect.name != "postgresql":
            return
        resolved = statements() if callable(statements) else statements
        for statement in resolved:
            connection.execute(text(statement))


def managed_postgres_index_names() -> frozenset[str]:
    """Index names created by the PostgreSQL ``after_create`` hooks."""
    return frozenset(_MANAGED_INDEX_NAMES)
