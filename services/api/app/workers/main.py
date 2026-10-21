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
import os
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
    # Same log shape as the API process, so one log query covers both.
    from ..observability import configure_logging, init_observability

    configure_logging("worker")

    # The worker is a separate process from the API, and sentry_sdk patches
    # handlers in-process only. Without this call every failure in the
    # outbox/review/localith/post-publish loops is invisible in GlitchTip.
    init_observability("worker")

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
    from ..modules.channels.meta.meta_events_worker import run_meta_events_worker
    from ..modules.channels.meta.lead_action_worker import run_lead_action_worker
    from ..modules.channels.meta.digest_worker import run_lead_digest_sweeps
    from ..modules.channels.meta.escalation_worker import run_escalation_sweeps
    from ..modules.channels.reviews_worker import run_google_reviews_worker
    from ..modules.jobs.reaper import run_job_reaper
    from ..modules.jobs.runner import JobRunner
    from ..modules.localith.worker import run_localith_sync_worker
    from ..modules.posts.worker import run_post_publish_worker

    loops = {
        "google-reviews-auto-reply": run_google_reviews_worker,
        "localith-sync": run_localith_sync_worker,
        "post-publisher": run_post_publish_worker,
        "analytics-consumer": run_analytics_consumer,
        "performance-sync": run_performance_sync_worker,
        "messaging-rollup": run_messaging_rollup_worker,
        "meta-events-ai-replies": run_meta_events_worker,
        "lead-actions": run_lead_action_worker,
        # Job queue lanes — unified job processing (Phase 0+1).
        # Each JobRunner claims jobs from Postgres (SKIP LOCKED), runs the
        # handler, records outcome, commits Kafka offset.
        "job-runner-realtime": lambda: JobRunner(lane="realtime", worker_id="realtime-1").start(),
        "job-runner-publishing": lambda: JobRunner(lane="publishing", worker_id="publishing-1").start(),
        "job-runner-media": lambda: JobRunner(lane="media", worker_id="media-1").start(),
        "job-runner-bulk": lambda: JobRunner(lane="bulk", worker_id="bulk-1").start(),
        # Lease reaper + `accepted` reconciler — returns crashed workers'
        # jobs to the queue and un-strands rows the dispatcher never
        # promoted.
        "job-reaper": run_job_reaper,
        # Reminder + handover resume for escalated leads. Cheap enough to run
        # everywhere; an AI-only deployment still wants the 24h resume, since
        # that is what stops a misrouted escalation silencing a customer.
        "escalation-sweeps": run_escalation_sweeps,
        # Daily pending-leads summary, hourly poll, one send per tenant per
        # local day. Opt-in per tenant, so it is inert until enabled.
        "lead-digest": run_lead_digest_sweeps,
    }
    # Deployment-only split by role, no code changes: WORKER_LOOPS is a
    # comma-separated allowlist of loop names ("meta-events-ai-replies,
    # lead-actions" -> an AI-only container on the same image). Unknown
    # names fail fast — a typo'd env var must not silently run nothing.
    # Unset = every loop, the default single-container topology.
    only = os.environ.get("WORKER_LOOPS", "").strip()
    if only:
        wanted = {name.strip() for name in only.split(",") if name.strip()}
        unknown = wanted - loops.keys()
        if unknown:
            raise SystemExit(
                "WORKER_LOOPS names unknown loops: "
                f"{', '.join(sorted(unknown))} (known: {', '.join(sorted(loops))})"
            )
        loops = {name: fn for name, fn in loops.items() if name in wanted}

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
