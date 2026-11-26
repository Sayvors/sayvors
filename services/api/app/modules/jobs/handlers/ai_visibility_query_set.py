"""Registry adapter for business-aware AI-visibility query-set jobs."""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...ai_visibility.batch_jobs import handle_query_set


async def handle(job: Any, db: AsyncSession) -> dict[str, Any]:
    return await handle_query_set(job, db)
