from fastapi import APIRouter, Depends, status

from ...core.deps import get_current_user
from ..users.models import User
from .client import get_redis

router = APIRouter(prefix="/api/v1/redis", tags=["redis"])


@router.get("/health")
async def redis_health(user: User = Depends(get_current_user)):
    try:
        r = await get_redis()
        await r.ping()
        return {"status": "ok"}
    except Exception as e:
        # Detail goes to logs only — driver errors can carry internal
        # host/port topology that must not reach clients.
        import logging

        logging.getLogger(__name__).warning("Redis health check failed: %s", e)
        return {"status": "error", "detail": "Redis is unavailable"}
