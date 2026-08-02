from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .modules.users.router import router as users_router
from .modules.tts.router import router as tts_router
from .modules.stt.router import router as stt_router
from .modules.llm.router import router as llm_router
from .modules.channels.router import router as channels_router
from .modules.redis.router import router as redis_router
from .modules.kafka.router import router as kafka_router

app = FastAPI(title="Sayvors API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── register modules ────────────────────────────────────
# each module's router is imported and included here
app.include_router(users_router)
app.include_router(tts_router)
app.include_router(stt_router)
app.include_router(llm_router)
app.include_router(channels_router)
app.include_router(redis_router)
app.include_router(kafka_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
