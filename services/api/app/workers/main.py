"""Worker entrypoint: `python -m app.workers`.

Runs every queue/poll workload OUTSIDE the HTTP process — the WhatsApp
AI reply pipeline (webhook events -> LLM -> Cloud API send), the Google
Reviews auto-reply worker, the Localith background sync, the scheduled
post publisher, the analytics Kafka consumer + performance sync, and the
outbox drainer. These are the same loops the API's lifespan used to run
inline; isolating them guarantees dashboard traffic can never delay a
message reply, and the worker scales independently of the API.

The api service sets RUN_BACKGROUND_WORKERS=false in the worker
deployment (docker-compose worker service). Locally the flag defaults
true so a single uvicorn process stays self-sufficient.
"""
import asyncio
import logging
import signal

from ..config import settings
from ..database import engine
from ..modules.kafka.client import close_kafka, get_kafka_producer
from ..modules.outbox.worker import OutboxWorker
from ..modules.redis.client import close_redis, get_redis, mark_redis_unavailable

logger = logging.getLogger("app.worker")


async def _warmup() -> None:
    """Same readiness steps as the API lifespan — the worker is not a
    second-class deployable and needs the DB pool, LLM provider keys
    (the AI reply pipeline resolves models at generation time), Redis and
    Kafka before its loops start. Every step degrades gracefully."""
    import sqlalchemy as sa

    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
        logger.info("Database pool warmed up")
    except Exception as e:
        logger.error("Database pool warmup failed: %s", e)

    try:
        from ..modules.llm.providers.registry import refresh_provider_keys

        n = await refresh_provider_keys()
        logger.info("LLM provider keys loaded from DB: %d", n)
    except Exception as e:
        logger.warning("LLM provider key refresh failed (env fallback active): %s", e)

    try:
        redis = await get_redis()
        await redis.ping()
        logger.info("Redis connected")
    except Exception:
        mark_redis_unavailable()

    try:
        await get_kafka_producer()
        logger.info("Kafka connected")
    except Exception:
        from ..modules.kafka.client import mark_kafka_unavailable

        mark_kafka_unavailable()


async def _amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.RUN_BACKGROUND_WORKERS:
        # Guard against a misconfigured deploy where BOTH api and worker
        # run with the flag flipped the wrong way: the worker entrypoint
        # exists to run the loops, so an explicit false here is a mistake.
        logger.warning(
            "RUN_BACKGROUND_WORKERS=false on the worker entrypoint is "
            "ignored — this process exists to run the workers"
        )

    await _warmup()

    from ..modules.analytics.consumer import run_analytics_consumer
    from ..modules.analytics.messaging_rollup import run_messaging_rollup_worker
    from ..modules.analytics.performance import run_performance_sync_worker
    from ..modules.channels.meta.consumer import run_meta_events_consumer
    from ..modules.channels.meta.followup_worker import run_followup_worker
    from ..modules.channels.reviews_worker import run_google_reviews_worker
    from ..modules.localith.worker import run_localith_sync_worker
    from ..modules.posts.worker import run_post_publish_worker

    loops = {
        "google-reviews-auto-reply": run_google_reviews_worker,
        "localith-sync": run_localith_sync_worker,
        "post-publisher": run_post_publish_worker,
        "analytics-consumer": run_analytics_consumer,
        "performance-sync": run_performance_sync_worker,
        "messaging-rollup": run_messaging_rollup_worker,
        "meta-events-ai-replies": run_meta_events_consumer,
        "whatsapp-followups": run_followup_worker,
    }
    tasks = [asyncio.create_task(fn(), name=name) for name, fn in loops.items()]

    outbox_worker = OutboxWorker()
    await outbox_worker.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows dev: no add_signal_handler — Ctrl+C raises
            # KeyboardInterrupt out of asyncio.run instead.
            pass

    logger.info(
        "Worker up — running: %s + outbox-drainer", ", ".join(loops)
    )
    await stop.wait()

    logger.info("Shutdown: cancelling worker loops")
    for task in tasks:
        task.cancel()
    await outbox_worker.stop()
    try:
        producer = await get_kafka_producer()
        await producer.flush()
    except Exception:
        pass
    await close_redis()
    await close_kafka()
    logger.info("Worker stopped cleanly")


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
