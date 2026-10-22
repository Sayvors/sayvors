import logging
from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

logger = logging.getLogger(__name__)

# The pgvector codec can only be registered on a database that has the
# extension. On one that does not, the failure is logged once - not on every
# connection.
_vector_codec_logged = False

# ── Writer engine (primary / PgBouncer) ──────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_POOL_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS),
            "idle_in_transaction_session_timeout": str(settings.DB_IDLE_IN_TX_TIMEOUT_MS),
        }
    },
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ── Reader engine (replica / PgBouncer reader) ───────────────────────
# When DATABASE_READER_URL is empty, reads fall back to the writer engine.
_reader_url = settings.DATABASE_READER_URL or settings.DATABASE_URL
engine_read = create_async_engine(
    _reader_url,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_POOL_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args={
        "server_settings": {
            "statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS),
            "idle_in_transaction_session_timeout": str(settings.DB_IDLE_IN_TX_TIMEOUT_MS),
        }
    },
)
async_session_read = async_sessionmaker(engine_read, class_=AsyncSession, expire_on_commit=False)


async def _register_vector_codec(connection) -> None:
    """Teach asyncpg the pgvector ``vector`` type.

    SQLAlchemy's ``Vector`` type hands the driver the text form
    (``[1.0,2.0]``), so the codec passes that through untouched and parses
    the text the server sends back. Without a codec, asyncpg cannot encode
    a vector parameter at all and every embedding write fails with
    "unsupported type".
    """
    from pgvector import Vector

    def _encode(value):
        if isinstance(value, str):
            return value
        if isinstance(value, Vector):
            return value.to_text()
        return "[" + ",".join(str(float(item)) for item in value) + "]"

    await connection.set_type_codec(
        "vector",
        encoder=_encode,
        decoder=Vector.from_text,
        format="text",
    )


def _register_vector_on_connect(dbapi_connection, connection_record) -> None:
    """Pool hook: register the vector codec on every new connection.

    Skipped entirely when embeddings are off: the column is then a TEXT
    placeholder, nothing ever writes a vector, and probing for the type on
    every new pooled connection only produces a misleading warning.
    A database with embeddings enabled but no extension still boots: the
    codec registration is logged once and skipped.
    """
    global _vector_codec_logged
    if not settings.embeddings_enabled:
        return
    if not hasattr(dbapi_connection, "run_async"):
        return
    try:
        dbapi_connection.run_async(_register_vector_codec)
    except Exception as e:  # pragma: no cover - depends on the database
        if not _vector_codec_logged:
            _vector_codec_logged = True
            logger.warning(
                "pgvector codec not registered (%s) - this database has no "
                "vector extension. Databank vector search is unavailable "
                "until pgvector is installed and the migrations are applied "
                "(docs/database/migration-safety.md §9).",
                e,
            )


event.listen(engine.sync_engine, "connect", _register_vector_on_connect)
event.listen(engine_read.sync_engine, "connect", _register_vector_on_connect)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Writer session — for INSERT / UPDATE / DELETE (goes to primary)."""
    async with async_session() as session:
        yield session


async def get_db_read() -> AsyncGenerator[AsyncSession, None]:
    """Reader session — for SELECT only (goes to replica when configured)."""
    async with async_session_read() as session:
        yield session
