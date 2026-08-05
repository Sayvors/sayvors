from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings
from .modules.auth.router import router as auth_router
from .modules.tts.router import router as tts_router
from .modules.stt.router import router as stt_router
from .modules.llm.router import router as llm_router
from .modules.channels.router import router as channels_router
from .modules.redis.router import router as redis_router
from .modules.kafka.router import router as kafka_router
from .modules.rag.router import router as rag_router
from .modules.redis.client import close_redis
from .modules.kafka.client import close_kafka


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection: validate X-CSRF-Token header against csrf_token cookie."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Skip CSRF for login/signup/forgot/reset/verify (they set the cookie)
        skip_paths = {"/api/v1/auth/login", "/api/v1/auth/signup", "/api/v1/auth/refresh",
                      "/api/v1/auth/forgot-password", "/api/v1/auth/reset-password",
                      "/api/v1/auth/verify-email", "/api/v1/auth/csrf-token", "/health"}
        if request.url.path in skip_paths:
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
    # Startup: warm up Redis and Kafka connections
    try:
        from .modules.redis.client import get_redis
        await get_redis()
    except Exception:
        pass
    try:
        from .modules.kafka.client import get_kafka_producer
        await get_kafka_producer()
    except Exception:
        pass
    yield
    # Shutdown
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

# ── register modules ────────────────────────────────────
app.include_router(auth_router)
app.include_router(tts_router)
app.include_router(stt_router)
app.include_router(llm_router)
app.include_router(channels_router)
app.include_router(redis_router)
app.include_router(kafka_router)
app.include_router(rag_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
