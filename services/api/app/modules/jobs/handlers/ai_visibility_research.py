"""Registry adapter for grounded AI-visibility research jobs."""
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ...ai_visibility.jobs import handle_research


async def handle(job: Any, db: AsyncSession) -> dict[str, Any]:
    return await handle_research(job, db)
