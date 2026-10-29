from contextlib import asynccontextmanager
from uuid import uuid4
import json
import logging

logger = logging.getLogger(__name__)
import sys
import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import settings
from .modules.auth.router import router as auth_router
from .modules.users.account import router as account_router
from .modules.tts.router import router as tts_router
from .modules.stt.router import router as stt_router
from .modules.llm.router import router as llm_router
from .modules.channels.leads import router as leads_router
from .modules.channels.review_issues import router as review_issues_router
from .modules.channels.customers_router import router as customers_router
from .modules.channels.router import _inbox_router as inbox_router
from .modules.channels.router import router as channels_router
from .modules.channels.publish.router import router as publish_router
from .modules.catalog.router import router as catalog_router
from .modules.channels.meta.router import router as meta_router
from .modules.channels.meta.webhooks.router import router as meta_webhooks_router
from .modules.redis.router import router as redis_router
from .modules.kafka.router import router as kafka_router
from .modules.rag.router import router as rag_router
from .modules.analytics.router import router as analytics_router
from .modules.analytics.abuse_router import router as analytics_abuse_router
from .modules.profile.router import router as profile_router
from .modules.onboarding.router import router as onboarding_router
from .modules.localith.router import router as localith_router
from .modules.locations.router import router as locations_router
from .modules.posts.router import router as posts_router
from .modules.media.router import router as media_router
from .modules.storage.router import router as storage_router
from .modules.admin.models import AdminAuditLog
from .modules.admin.router import router as admin_router
from .modules.admin import models as _admin_models  # noqa: F401 (registers tables)
from .modules.user_feedback.router import router as feedback_router
from .modules.email.router import router as email_router
from .modules.review_engine.router import router as review_engine_router
from .modules.review_engine.csv_router import router as csv_router
from .modules.assistant.router import router as assistant_router
from .modules.notifications.router import router as notifications_router
from .modules.billing.router import router as billing_router
from .modules.jobs.router import router as jobs_router, admin_router as jobs_admin_router
from .modules.team.router import router as team_router
from .modules.redis.client import close_redis
from .modules.kafka.client import close_kafka


# ── Logging ──────────────────────────────────────────────────────────────
# Implementation lives in app.observability so the worker process emits the
# same shape; re-exported here for existing importers. The format itself is
# chosen per stream there (console when a TTY, JSON when piped).
from .observability import (
    ConsoleFormatter,
    JsonFormatter,
    configure_logging as _configure_logging,
)


def setup_logging():
    """Configure logging for the API process."""
    _configure_logging("api")


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
# ── In-process metrics (Prometheus exposition format) ────────────────
# Kept dependency-free: a small in-memory counter/histogram exposed at /metrics.
# For multi-replica deploys, Prometheus scrapes each replica individually.
_METRICS_REQUEST_COUNT = 0
_METRICS_LATENCY_BUCKETS_SECONDS = [
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10,
]
_METRICS_LATENCY_COUNTS = [0] * len(_METRICS_LATENCY_BUCKETS_SECONDS)
_METRICS_LATENCY_SUM = 0.0


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
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
            _observe_request(process_time)
            return response
        except Exception as e:
            process_time = time.perf_counter() - start_time
            logger.exception(
                "%s %s failed: %s %.4fs",
                request.method, request.url.path, e, process_time,
                extra={"request_id": request_id},
            )
            _observe_request(process_time)
            raise


def _observe_request(process_time: float) -> None:
    global _METRICS_REQUEST_COUNT, _METRICS_LATENCY_SUM
    _METRICS_REQUEST_COUNT += 1
    _METRICS_LATENCY_SUM += process_time
    for i, le in enumerate(_METRICS_LATENCY_BUCKETS_SECONDS):
        if process_time <= le:
            _METRICS_LATENCY_COUNTS[i] += 1
            break
    else:
        _METRICS_LATENCY_COUNTS[-1] += 1


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


class AdminAuditMiddleware(BaseHTTPMiddleware):
    """Best-effort audit log for every /api/v1/admin/* request (except login,
    which is audited explicitly in the login handler)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path
        if not path.startswith("/api/v1/admin/") or path == "/api/v1/admin/login":
            return response
        # Audit *actions*, not reads: GET/HEAD/OPTIONS never mutate state, so
        # logging them only inflates admin_audit_logs (and its write load) with
        # polling/page-load noise. Mutations (POST/PATCH/PUT/DELETE) are the
        # security-relevant events worth retaining.
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return response
        # Resolved inside the try, but declared here so the failure log can
        # name the operator even when the exception happens during resolution.
        operator_id = None
        operator_username = None
        try:
            from .database import async_session
            from .modules.admin.models import AdminAuditLog, PlatformOperator
            from .security import decode_token

            token = request.cookies.get(settings.ADMIN_COOKIE_NAME, "")
            if not token:
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    token = auth[7:]
            if token:
                try:
                    payload = decode_token(token)
                    if payload.get("type") == "admin":
                        operator_id = payload.get("sub")
                        if operator_id == "admin":
                            operator_username = "legacy-admin"
                            operator_id = None
                except Exception:
                    pass
            if operator_id:
                try:
                    async with async_session() as db:
                        op_row = await db.get(PlatformOperator, operator_id)
                        if op_row is not None:
                            operator_username = op_row.username
                except Exception:
                    pass
            ip = request.client.host if request.client else None
            async with async_session() as db:
                db.add(AdminAuditLog(
                    operator_id=operator_id,
                    operator_username=operator_username,
                    action=f"{request.method} {path}",
                    method=request.method,
                    path=path[:256],
                    status_code=response.status_code,
                    ip=ip,
                    user_agent=request.headers.get("user-agent"),
                ))
                await db.commit()
        except Exception as e:
            # Best-effort by design, but a dead audit trail must not be silent:
            # debug-level logging makes a broken trail look identical to a
            # working one at default log levels.
            logger.warning(
                "Admin audit write failed: path=%s operator=%s error=%s",
                path,
                operator_username or operator_id or "unresolved",
                e,
                exc_info=True,
            )
        return response


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

    # Catalog rows are data, not schema: a models-only rebuild creates the
    # tables but leaves them empty, and then every tone is invalid and no
    # strategy matches. The seeder is idempotent and never overwrites an
    # admin edit, so it is safe on every boot and from every worker.
    try:
        from .database import async_session
        from .modules.review_engine.catalog_seed import seed_catalogs

        async with async_session() as db:
            seeded = await seed_catalogs(db)
        log.info("Catalog seed inserted: %s", seeded)
    except Exception as e:
        log.error(
            "Catalog seed failed — tones/dialects/strategies may stay empty "
            "until the next start: %s",
            e,
        )

    # Bootstrap the first platform operator if none exist (replaces the
    # shared admin password with named accounts on first boot).
    try:
        from .database import async_session
        from .modules.admin.models import PlatformOperator
        from .security import hash_password
        from sqlalchemy import select, func

        async with async_session() as db:
            count = (await db.execute(select(func.count()).select_from(PlatformOperator))).scalar() or 0
            if count == 0:
                bootstrap_user = settings.ADMIN_BOOTSTRAP_USERNAME if hasattr(settings, "ADMIN_BOOTSTRAP_USERNAME") else None
                bootstrap_pw = settings.ADMIN_BOOTSTRAP_PASSWORD if hasattr(settings, "ADMIN_BOOTSTRAP_PASSWORD") else None
                # Fallback: migrate the legacy shared password into an "admin" operator.
                if not bootstrap_user and settings.ADMIN_PASSWORD_HASH:
                    # Can't reverse the hash; create a placeholder that must be
                    # reset. Log a warning so the operator knows to set a real one.
                    bootstrap_user = "admin"
                    bootstrap_pw = None
                if bootstrap_user:
                    import uuid as _uuid
                    import secrets as _secrets

                    if bootstrap_pw:
                        pw_hash = hash_password(bootstrap_pw)
                    else:
                        pw_hash = settings.ADMIN_PASSWORD_HASH or hash_password(_secrets.token_urlsafe(32))
                    db.add(PlatformOperator(
                        id=str(_uuid.uuid4()),
                        username=bootstrap_user,
                        password_hash=pw_hash,
                        role="superadmin",
                        is_active=True,
                    ))
                    await db.commit()
                    log.warning(
                        "Bootstrapped platform operator '%s'. Set ADMIN_BOOTSTRAP_USERNAME/PASSWORD "
                        "or rotate the password immediately.", bootstrap_user
                    )
    except Exception as e:
        log.warning("Platform operator bootstrap failed: %s", e)
    try:
        from .modules.llm.providers.registry import refresh_provider_keys
        n = await refresh_provider_keys()
        log.info("LLM provider keys loaded from DB: %d", n)
    except Exception as e:
        log.warning("LLM provider key refresh failed — generation stays unavailable until it succeeds: %s", e)

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
    from .modules.redis.client import run_redis_rearmer
    retention_task = asyncio.create_task(run_retention_loop())

    # Redis re-armer runs in the API process, not only the worker deployment.
    # A boot-time Redis blip latches the client offline; get_redis() re-probes
    # on demand after a cooldown, but with no traffic that recovery never
    # happens and the first request after the outage pays a failed 2s connect.
    # The prober unlatches it on a fixed interval regardless of traffic.
    redis_rearmer_task = asyncio.create_task(run_redis_rearmer())

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
        from .modules.analytics.insights_worker import run_conversation_insights_worker
        from .modules.analytics.market_benchmarks_worker import run_market_benchmarks_worker
        from .modules.analytics.follower_snapshot_worker import run_follower_snapshot_worker
        from .modules.channels.meta.meta_events_worker import run_meta_events_worker
        from .modules.channels.meta.lead_action_worker import run_lead_action_worker
        from .modules.billing.ledger import run_hold_reaper
        from .modules.outbox.worker import OutboxWorker

        bg_tasks.append(asyncio.create_task(run_hold_reaper()))
        bg_tasks.append(asyncio.create_task(run_google_reviews_worker()))
        bg_tasks.append(asyncio.create_task(run_localith_sync_worker()))
        bg_tasks.append(asyncio.create_task(run_post_publish_worker()))
        bg_tasks.append(asyncio.create_task(run_analytics_consumer()))
        bg_tasks.append(asyncio.create_task(run_performance_sync_worker()))
        bg_tasks.append(asyncio.create_task(run_messaging_rollup_worker()))
        bg_tasks.append(asyncio.create_task(run_conversation_insights_worker()))
        bg_tasks.append(asyncio.create_task(run_market_benchmarks_worker()))
        bg_tasks.append(asyncio.create_task(run_follower_snapshot_worker()))
        bg_tasks.append(asyncio.create_task(run_meta_events_worker()))
        bg_tasks.append(asyncio.create_task(run_lead_action_worker()))

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
    redis_rearmer_task.cancel()
    for task in bg_tasks:
        task.cancel()
    await asyncio.gather(retention_task, redis_rearmer_task, *bg_tasks, return_exceptions=True)
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
app.add_middleware(AdminAuditMiddleware)
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

# ── Domain exception handlers ────────────────────────────────────────
# EntitlementDenied -> 403 so callers see a clear "plan limit" error
# instead of a 500. Fail-closed: a denied feature never silently passes.
from .modules.billing.entitlements import EntitlementDenied

@app.exception_handler(EntitlementDenied)
async def _entitlement_denied_handler(request, exc):
    from fastapi import HTTPException

    raise HTTPException(status_code=403, detail=str(exc))
# Routers are imported at the top of this module; only registration happens
# here. Re-importing them lower down shadowed nothing but left two copies of
# every import to keep in sync.
app.include_router(auth_router)
app.include_router(account_router)
app.include_router(tts_router)
app.include_router(stt_router)
app.include_router(llm_router)
# Publish is registered BEFORE channels on purpose: the channels router owns
# GET /api/v1/channels/{channel_id}, so registering it first would swallow
# GET /api/v1/channels/publish (the posts feed) as a channel lookup.
app.include_router(publish_router)
app.include_router(catalog_router)
app.include_router(channels_router)
app.include_router(leads_router)
app.include_router(review_issues_router)
app.include_router(customers_router)
app.include_router(inbox_router)
app.include_router(meta_router)
app.include_router(meta_webhooks_router)
app.include_router(analytics_router)
app.include_router(analytics_abuse_router)
app.include_router(redis_router)
app.include_router(kafka_router)
app.include_router(rag_router)
app.include_router(profile_router)
app.include_router(onboarding_router)
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
app.include_router(jobs_router)
app.include_router(jobs_admin_router)
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


@app.get("/metrics")
async def metrics():
    """Prometheus exposition format — scrapable by Prometheus / Grafana Cloud.

    Returns in-process request count + latency histogram. One scrape target per
    replica; aggregate across replicas in Prometheus/Grafana.
    """
    global _METRICS_REQUEST_COUNT, _METRICS_LATENCY_SUM
    total_count = sum(_METRICS_LATENCY_COUNTS)
    lines: list[str] = [
        "# HELP sayvors_http_requests_total Total HTTP requests handled by this replica.",
        "# TYPE sayvors_http_requests_total counter",
        f"sayvors_http_requests_total {_METRICS_REQUEST_COUNT}",
        "",
        "# HELP sayvors_http_request_duration_seconds HTTP request latency in seconds.",
        "# TYPE sayvors_http_request_duration_seconds histogram",
    ]
    cumulative = 0
    for le, count in zip(_METRICS_LATENCY_BUCKETS_SECONDS, _METRICS_LATENCY_COUNTS):
        cumulative += count
        lines.append(f'sayvors_http_request_duration_seconds_bucket{{le="{le}"}} {cumulative}')
    lines.append(f'sayvors_http_request_duration_seconds_bucket{{le="+Inf"}} {total_count}')
    lines.append(f"sayvors_http_request_duration_seconds_sum {_METRICS_LATENCY_SUM}")
    lines.append(f"sayvors_http_request_duration_seconds_count {total_count}")
    lines.append("")

    # Job queue metrics (dependency-free, queries Postgres)
    try:
        from .modules.jobs.service import get_queue_metrics

        qm = await get_queue_metrics()
        lines.append("# HELP sayvors_job_queue_depth Number of queued+retrying jobs per lane.")
        lines.append("# TYPE sayvors_job_queue_depth gauge")
        for lane, depth in qm.get("depth", {}).items():
            lines.append(f'sayvors_job_queue_depth{{lane="{lane}"}} {depth}')
        lines.append("")
        lines.append("# HELP sayvors_job_oldest_age_seconds Age of oldest queued job per lane.")
        lines.append("# TYPE sayvors_job_oldest_age_seconds gauge")
        for lane, age in qm.get("oldest_age", {}).items():
            lines.append(f'sayvors_job_oldest_age_seconds{{lane="{lane}"}} {age}')
        lines.append("")
    except Exception:
        pass

    # Redis health/memory. Rate limits, the token blacklist, sessions and OTPs
    # all live in Redis, so a scrape is also the honest liveness signal for the
    # auth path. maxmemory is 128 MB in dev and 1-2 GB in the target topology;
    # alert at 75% of it.
    lines.append("# HELP sayvors_redis_available Redis reachable from this replica (1/0).")
    lines.append("# TYPE sayvors_redis_available gauge")
    try:
        from .modules.redis.client import get_redis

        redis = await get_redis()
        info = await redis.info("memory")
        used = int(info.get("used_memory") or 0)
        maxmemory = int(info.get("maxmemory") or 0)
        lines.append("sayvors_redis_available 1")
        lines.append("# HELP sayvors_redis_used_memory_bytes Redis used_memory in bytes.")
        lines.append("# TYPE sayvors_redis_used_memory_bytes gauge")
        lines.append(f"sayvors_redis_used_memory_bytes {used}")
        lines.append("# HELP sayvors_redis_maxmemory_bytes Redis maxmemory in bytes (0 = unlimited).")
        lines.append("# TYPE sayvors_redis_maxmemory_bytes gauge")
        lines.append(f"sayvors_redis_maxmemory_bytes {maxmemory}")
        if maxmemory > 0:
            lines.append("# HELP sayvors_redis_memory_utilization_ratio used_memory divided by maxmemory.")
            lines.append("# TYPE sayvors_redis_memory_utilization_ratio gauge")
            lines.append(f"sayvors_redis_memory_utilization_ratio {used / maxmemory:.4f}")
    except Exception:
        # Fail closed for the metric, not for the app: an unreachable Redis is
        # already handled by the auth paths; the scrape must still succeed.
        lines.append("sayvors_redis_available 0")
    lines.append("")

    return Response(
        content="\n".join(lines),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )