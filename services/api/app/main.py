from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import settings
from .modules.auth.router import router as auth_router
from .modules.tts.router import router as tts_router
from .modules.stt.router import router as stt_router
from .modules.llm.router import router as llm_router
from .modules.channels.router import router as channels_router
from .modules.redis.router import router as redis_router
from .modules.kafka.router import router as kafka_router
from .modules.rag.router import router as rag_router
from .modules.analytics.router import router as analytics_router
from .modules.profile.router import router as profile_router
from .modules.localith.router import router as localith_router
from .modules.email.router import router as email_router
from .modules.redis.client import close_redis
from .modules.kafka.client import close_kafka


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection: validate X-CSRF-Token header against csrf_token cookie."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Exempt paths: auth endpoints, webhooks, health
        path = request.url.path
        skip_prefixes = (
            "/api/v1/auth/login", "/api/v1/auth/signup", "/api/v1/auth/refresh",
            "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password",
            "/api/v1/auth/verify-email", "/api/v1/auth/csrf-token",
            "/api/v1/channels/webhook/",
            "/health",
        )
        if any(path.startswith(p) for p in skip_prefixes):
            return await call_next(request)

        csrf_header = request.headers.get("x-csrf-token")
        csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)

        if not csrf_header or not csrf_cookie or csrf_header != csrf_cookie:
            return Response(
                content='{"detail":"CSRF validation failed"}',
                status_code=403,
                media_type="application/json",
            )

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    log = logging.getLogger(__name__)

    # Warm up database connection pool (critical for first-request speed)
    try:
        from .database import engine
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        log.info("Database pool warmed up")
    except Exception as e:
        log.error("Database pool warmup failed: %s", e)

    # Try Redis — mark unavailable fast if down
    try:
        from .modules.redis.client import get_redis
        redis = await get_redis()
        await redis.ping()
        log.info("Redis connected")
    except Exception:
        from .modules.redis.client import mark_redis_unavailable
        mark_redis_unavailable()

    # Try Kafka — mark unavailable fast if down (5s timeout)
    try:
        from .modules.kafka.client import get_kafka_producer
        await get_kafka_producer()
        log.info("Kafka connected")
    except Exception:
        from .modules.kafka.client import mark_kafka_unavailable
        mark_kafka_unavailable()

    # Run retention cleanup on startup
    try:
        from .database import async_session
        from .modules.auth.service import cleanup_expired_data
        async with async_session() as db:
            result = await cleanup_expired_data(db)
            log.info(
                "Retention cleanup: deleted %d login attempts, %d refresh tokens",
                result["login_attempts_deleted"],
                result["refresh_tokens_deleted"],
            )
    except Exception:
        pass

    # Schedule periodic retention cleanup (startup-only runs never fire again
    # on long-lived pods)
    import asyncio
    from .modules.auth.service import run_retention_loop
    retention_task = asyncio.create_task(run_retention_loop())

    # Start the Google Reviews auto-reply polling worker
    from .modules.channels.reviews_worker import run_google_reviews_worker
    reviews_task = asyncio.create_task(run_google_reviews_worker())

    # Start the analytics pipeline: Kafka consumer (review enrichment +
    # daily rollups) and Google performance metrics sync worker
    from .modules.analytics.consumer import run_analytics_consumer
    from .modules.analytics.performance import run_performance_sync_worker
    analytics_consumer_task = asyncio.create_task(run_analytics_consumer())
    performance_sync_task = asyncio.create_task(run_performance_sync_worker())

    # Start the outbox worker (drains events to Kafka)
    from .modules.outbox.worker import OutboxWorker
    outbox_worker = OutboxWorker()
    await outbox_worker.start()

    yield

    # Shutdown
    retention_task.cancel()
    reviews_task.cancel()
    analytics_consumer_task.cancel()
    performance_sync_task.cancel()
    await outbox_worker.stop()
    try:
        from .modules.kafka.client import get_kafka_producer
        producer = await get_kafka_producer()
        await producer.flush()
    except Exception:
        pass
    await close_redis()
    await close_kafka()


app = FastAPI(title="Sayvors API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    expose_headers=["X-CSRF-Token"],
)
app.add_middleware(CSRFMiddleware)
if settings.ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# ── register modules ────────────────────────────────────
app.include_router(auth_router)
app.include_router(tts_router)
app.include_router(stt_router)
app.include_router(llm_router)
app.include_router(channels_router)
app.include_router(analytics_router)
app.include_router(redis_router)
app.include_router(kafka_router)
app.include_router(rag_router)
app.include_router(profile_router)
app.include_router(localith_router)
app.include_router(email_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
