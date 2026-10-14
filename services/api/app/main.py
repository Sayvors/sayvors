from contextlib import asynccontextmanager
from uuid import uuid4
import logging
import json
import sys
import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import settings
from .modules.auth.router import router as auth_router
from .modules.tts.router import router as tts_router
from .modules.stt.router import router as stt_router
from .modules.llm.router import router as llm_router
from .modules.channels.leads import router as leads_router
from .modules.channels.review_issues import router as review_issues_router
from .modules.channels.router import _inbox_router as inbox_router
from .modules.channels.router import router as channels_router
from .modules.channels.meta.router import router as meta_router
from .modules.channels.meta.webhooks.router import router as meta_webhooks_router
from .modules.redis.router import router as redis_router
from .modules.kafka.router import router as kafka_router
from .modules.rag.router import router as rag_router
from .modules.analytics.router import router as analytics_router
from .modules.analytics.abuse_router import router as analytics_abuse_router
from .modules.profile.router import router as profile_router
from .modules.localith.router import router as localith_router
from .modules.locations.router import router as locations_router
from .modules.posts.router import router as posts_router
from .modules.media.router import router as media_router
from .modules.storage.router import router as storage_router
from .modules.admin.router import router as admin_router
from .modules.user_feedback.router import router as feedback_router
from .modules.email.router import router as email_router
from .modules.review_engine.router import router as review_engine_router
from .modules.review_engine.csv_router import router as csv_router
from .modules.assistant.router import router as assistant_router
from .modules.notifications.router import router as notifications_router
from .modules.billing.router import router as billing_router
from .modules.team.router import router as team_router
from .modules.redis.client import close_redis
from .modules.kafka.client import close_kafka


# ── Structured JSON logging ──────────────────────────────────────────────
# Implementation lives in app.observability so the worker process emits the
# same JSON shape; re-exported here for existing importers.
from .observability import JsonFormatter, configure_json_logging as _configure_json_logging


def setup_logging():
    """Configure structured JSON logging for the API process."""
    _configure_json_logging("api")


# ── GlitchTip error tracking ─────────────────────────────────────────────
def setup_glitchtip():
    """Initialize GlitchTip error tracking for the API process.

    Configuration lives in app/observability.py so every entrypoint (api,
    worker) shares one source of truth. Re-exported here for callers that
    already import from app.main.
    """
    from .observability import init_observability

    return init_observability("api")


# ── Request-ID middleware ────────────────────────────────────────────────
class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        request.state.request_id = request_id

        logger = logging.getLogger(__name__)
        extra = {"request_id": request_id}

        if hasattr(request.state, "tenant_id"):
            extra["tenant_id"] = request.state.tenant_id

        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            process_time = time.perf_counter() - start_time
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.4f}"
            logger.info(
                "%s %s %d %.4fs",
                request.method, request.url.path, response.status_code, process_time,
                extra=extra,
            )
            return response
        except Exception as e:
            process_time = time.perf_counter() - start_time
            logger.exception(
                "%s %s failed: %s %.4fs",
                request.method, request.url.path, e, process_time,
                extra={"request_id": request_id},
            )
            raise


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection: validate X-CSRF-Token header against csrf_token cookie."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Exempt paths: auth endpoints, webhooks, health. Admin is exempt
        # as a whole: Bearer-header auth only, no CSRF confused deputy.
        path = request.url.path
        skip_prefixes = (
            "/api/v1/auth/login", "/api/v1/auth/signup", "/api/v1/auth/refresh",
            "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password",
            "/api/v1/auth/verify-email", "/api/v1/auth/verify-otp", "/api/v1/auth/csrf-token",
            "/api/v1/auth/google/verify",
            "/api/v1/auth/facebook/verify",
            "/api/v1/admin/",
            "/api/v1/email/otp/",
            "/api/v1/channels/webhook/",
            "/api/v1/meta/webhooks",
            "/api/v1/team/invites/accept",  # token-in-body is the proof; works pre-auth
            "/health",
        )
        if any(request.url.path.startswith(p) for p in skip_prefixes):
            return await call_next(request)

        csrf_header = request.headers.get("x-csrf-token")
        csrf_cookie = request.cookies.get(settings.CSRF_COOKIE_NAME)

        if not csrf_header or not csrf_cookie or csrf_header != csrf_cookie:
            # "CSRF validation failed" told the caller nothing and the operator
            # nothing at all. These three cases need different fixes: a missing
            # header means the client never read the cookie, a missing cookie
            # means the browser declined to send it (cross-site + SameSite), and
            # a mismatch usually means two cookies share the name and the client
            # and the server picked different ones. Never log the values.
            if not csrf_header:
                why = "no X-CSRF-Token header"
            elif not csrf_cookie:
                why = f"no {settings.CSRF_COOKIE_NAME} cookie sent"
            else:
                why = (
                    f"mismatch (header {len(csrf_header)} chars, cookie "
                    f"{len(csrf_cookie)} chars)"
                )
            # A duplicate cookie name is the usual cause of a mismatch: ours is
            # host-only, but a sibling environment on a sayvors.com subdomain
            # sets Domain=.sayvors.com and that one rides along to every
            # subdomain. Name the count so it is never a mystery again.
            cookie_count = sum(
                1
                for c in request.cookies.keys()
                if c == settings.CSRF_COOKIE_NAME
            )
            if cookie_count > 1:
                why += f"; {cookie_count} cookies share this name"
            # Module-level `logging` is imported at the top; the loggers used
            # elsewhere in this file are function-local, so resolve one here
            # rather than reaching for a name that does not exist at class scope.
            logging.getLogger("app.main").warning(
                "CSRF rejected %s %s from origin=%s: %s",
                request.method,
                request.url.path,
                request.headers.get("origin", "-"),
                why,
            )
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

    setup_logging()  # Initialize structured JSON logging
    setup_glitchtip()  # Initialize GlitchTip error tracking

    # Warm up database connection pool (critical for first-request speed)
    try:
        from .database import engine
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        log.info("Database pool warmed up")
    except Exception as e:
        log.error("Database pool warmup failed: %s", e)

    # Load DB-backed LLM provider keys (env fallback stays if this fails)
    try:
        from .modules.llm.providers.registry import refresh_provider_keys
        n = await refresh_provider_keys()
        log.info("LLM provider keys loaded from DB: %d", n)
    except Exception as e:
        log.warning("LLM provider key refresh failed (env fallback active): %s", e)

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

    # Schedule periodic retention cleanup
    import asyncio
    from .modules.auth.service import run_retention_loop
    retention_task = asyncio.create_task(run_retention_loop())

    # Queue/poll workers (AI replies, syncs, publishers, Kafka consumers)
    # belong OUTSIDE the HTTP process: in the worker deployment they run via
    # `python -m app.workers` and the api sets RUN_BACKGROUND_WORKERS=false,
    # so dashboard traffic can never delay the webhook -> AI reply pipeline.
    # Dev keeps the default true — one uvicorn process still does everything.
    bg_tasks: list[asyncio.Task] = []
    outbox_worker = None
    if settings.RUN_BACKGROUND_WORKERS:
        from .modules.channels.reviews_worker import run_google_reviews_worker
        from .modules.localith.worker import run_localith_sync_worker
        from .modules.posts.worker import run_post_publish_worker
        from .modules.analytics.consumer import run_analytics_consumer
        from .modules.analytics.messaging_rollup import run_messaging_rollup_worker
        from .modules.analytics.performance import run_performance_sync_worker
        from .modules.channels.meta.meta_events_worker import run_meta_events_worker
        from .modules.outbox.worker import OutboxWorker

        bg_tasks.append(asyncio.create_task(run_google_reviews_worker()))
        bg_tasks.append(asyncio.create_task(run_localith_sync_worker()))
        bg_tasks.append(asyncio.create_task(run_post_publish_worker()))
        bg_tasks.append(asyncio.create_task(run_analytics_consumer()))
        bg_tasks.append(asyncio.create_task(run_performance_sync_worker()))
        bg_tasks.append(asyncio.create_task(run_messaging_rollup_worker()))
        bg_tasks.append(asyncio.create_task(run_meta_events_worker()))

        outbox_worker = OutboxWorker()
        await outbox_worker.start()
    else:
        log.info(
            "RUN_BACKGROUND_WORKERS=false — queue/poll workers run in the "
            "worker deployment"
        )

    yield

    # Shutdown
    retention_task.cancel()
    for task in bg_tasks:
        task.cancel()
    if outbox_worker is not None:
        await outbox_worker.stop()
    try:
        from .modules.kafka.client import get_kafka_producer
        producer = await get_kafka_producer()
        await producer.flush()
    except Exception:
        pass
    await close_redis()
    await close_kafka()


app = FastAPI(title="Sayvors API", version="0.1.0", lifespan=lifespan, body_limit=100_000_000)

# ── Middleware ──────────────────────────────────────────────────────────
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "X-Requested-With"],
    expose_headers=["X-CSRF-Token", "X-Request-ID"],
)
app.add_middleware(CSRFMiddleware)
if settings.ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# ── register modules ──────────────────────────────────────────────────
# Routers are imported at the top of this module; only registration happens
# here. Re-importing them lower down shadowed nothing but left two copies of
# every import to keep in sync.
app.include_router(auth_router)
app.include_router(tts_router)
app.include_router(stt_router)
app.include_router(llm_router)
app.include_router(channels_router)
app.include_router(leads_router)
app.include_router(review_issues_router)
app.include_router(inbox_router)
app.include_router(meta_router)
app.include_router(meta_webhooks_router)
app.include_router(analytics_router)
app.include_router(analytics_abuse_router)
app.include_router(redis_router)
app.include_router(kafka_router)
app.include_router(rag_router)
app.include_router(profile_router)
app.include_router(localith_router)
app.include_router(locations_router)
app.include_router(posts_router)
app.include_router(media_router)
app.include_router(storage_router)
app.include_router(admin_router)
app.include_router(feedback_router)
app.include_router(email_router)
app.include_router(review_engine_router)
app.include_router(csv_router)
app.include_router(assistant_router)
app.include_router(notifications_router)
app.include_router(billing_router)
app.include_router(team_router)

# Public media files
try:
    import os as _os
    from fastapi.staticfiles import StaticFiles as _StaticFiles

    _os.makedirs(settings.MEDIA_DIR, exist_ok=True)
    app.mount(
        settings.MEDIA_PUBLIC_PATH,
        _StaticFiles(directory=settings.MEDIA_DIR, check_dir=False),
        name="media-files",
    )
except Exception:
    pass


# ── Health & readiness endpoints ───────────────────────────────────────
@app.get("/health")
async def health():
    """Liveness probe — is this process up and serving?

    Deliberately does NOT touch dependencies. A liveness check that fails when
    Postgres is slow makes the orchestrator restart an otherwise healthy
    process, turning a dependency blip into an outage. Dependency health is
    /readyz's job: it reports 503 so traffic stops being routed, without
    killing the container.
    """
    return {"status": "ok"}


@app.get("/readyz")
async def readyz(request: Request):
    """Readiness probe — checks DB, Redis, Kafka connectivity.

    Returns 503 when any dependency is unreachable so the orchestrator stops
    routing traffic to this instance. Liveness is /health, which deliberately
    ignores dependencies so a slow database never triggers a restart loop.
    """
    from .healthcheck import probe_dependencies

    checks = await probe_dependencies()
    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503

    return Response(
        content=json.dumps({"status": "ready" if all_ok else "degraded", "checks": checks}),
        media_type="application/json",
        status_code=status_code,
    )