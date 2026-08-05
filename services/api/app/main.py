from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
