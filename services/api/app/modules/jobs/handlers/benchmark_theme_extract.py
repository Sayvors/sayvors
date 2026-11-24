"""Thin registry adapter for the benchmark theme extraction worker."""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...benchmark.theme_jobs import handle_benchmark_theme_extract


async def handle(job: Any, db: AsyncSession) -> dict[str, Any]:
    return await handle_benchmark_theme_extract(job, db)
