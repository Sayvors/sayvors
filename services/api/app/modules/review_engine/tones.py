"""Response tone catalog — database-backed, admin-managed.

Mirrors the dialects module: the table is seeded by migration a2b3c4d5e6f7,
admins add or remove rows via POST/DELETE /api/v1/admin/tones, and the
Settings picker reads the table. Unknown/deleted codes pass through
untouched wherever they are referenced.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Tone


def to_dict(row: Tone) -> dict:
    return {
        "code": row.code,
        "label": row.label,
        "description": row.description or "",
    }


async def list_tones(db: AsyncSession) -> list[dict]:
    """All catalog rows, alphabetical by code (stable order)."""
    rows = (
        await db.execute(select(Tone).order_by(Tone.code))
    ).scalars().all()
    return [to_dict(r) for r in rows]


async def get_tone(code: str | None, db: AsyncSession) -> dict | None:
    """One catalog entry, or None for unknown codes."""
    if not code or not isinstance(code, str):
        return None
    row = await db.get(Tone, code.strip().lower())
    return to_dict(row) if row else None


async def is_valid_tone_db(code: str | None, db: AsyncSession) -> bool:
    """True when the code is present in the table."""
    if not isinstance(code, str) or not code:
        return False
    return (await db.get(Tone, code.strip().lower())) is not None
