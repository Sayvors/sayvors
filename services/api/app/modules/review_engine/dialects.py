"""Arabic dialect catalog — database-backed, admin-managed.

The table is seeded with 23 dialects by migration z1a2b3c4d5e6; admins add
or remove rows via POST/DELETE /api/v1/admin/dialects. Reply generation
reads this table — nothing here is hardcoded. Unknown/deleted codes fall
back to "auto" behavior wherever they are referenced.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Dialect

AUTO = "auto"


def to_dict(row: Dialect) -> dict:
    return {
        "code": row.code,
        "dialect_en": row.dialect_en,
        "dialect_ar": row.dialect_ar,
        "examples": list(row.examples or []),
    }


async def list_dialects(db: AsyncSession) -> list[dict]:
    """All catalog rows, alphabetical by code (stable order)."""
    rows = (
        await db.execute(select(Dialect).order_by(Dialect.code))
    ).scalars().all()
    return [to_dict(r) for r in rows]


async def get_dialect(code: str | None, db: AsyncSession) -> dict | None:
    """One catalog entry, or None for 'auto'/unknown (caller falls back)."""
    if not code or code == AUTO:
        return None
    row = await db.get(Dialect, code)
    return to_dict(row) if row else None


async def is_valid_dialect_db(code: str | None, db: AsyncSession) -> bool:
    """'auto' or a code present in the table."""
    if code == AUTO:
        return True
    if not isinstance(code, str) or not code:
        return False
    return (await db.get(Dialect, code)) is not None
