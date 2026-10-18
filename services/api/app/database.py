from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

# ── Writer engine (primary / PgBouncer) ──────────────────────────────
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_POOL_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_recycle=1800,
    pool_pre_ping=True,
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
)
async_session_read = async_sessionmaker(engine_read, class_=AsyncSession, expire_on_commit=False)


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
