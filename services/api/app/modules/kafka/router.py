from fastapi import APIRouter, Depends

from ...core.deps import get_current_user
from ..users.models import User
from .client import get_kafka_producer

router = APIRouter(prefix="/api/v1/kafka", tags=["kafka"])


@router.get("/health")
async def kafka_health(user: User = Depends(get_current_user)):
    try:
        producer = await get_kafka_producer()
        metadata = await producer.list_topics()
        return {"status": "ok", "topics": sorted(metadata.topics)}
    except Exception as e:
        # Detail goes to logs only — broker errors can carry internal
        # bootstrap-server topology that must not reach clients.
        import logging

        logging.getLogger(__name__).warning("Kafka health check failed: %s", e)
        return {"status": "error", "detail": "Kafka is unavailable"}
