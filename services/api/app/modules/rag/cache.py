import hashlib
import json

from ...modules.redis.client import get_redis

EMBED_CACHE_PREFIX = "sayvors:rag:embed:"
PARSE_CACHE_PREFIX = "sayvors:rag:parse:"
QUERY_CACHE_PREFIX = "sayvors:rag:query:"
PROGRESS_PREFIX = "sayvors:rag:job:"
QUEUE_KEY = "sayvors:rag:queue"
EMBED_CACHE_TTL = 86400 * 30


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


async def get_cached_embedding(text: str) -> list[float] | None:
    try:
        redis = await get_redis()
        key = EMBED_CACHE_PREFIX + content_hash(text)
        raw = await redis.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


async def set_cached_embedding(text: str, vector: list[float]) -> None:
    try:
        redis = await get_redis()
        key = EMBED_CACHE_PREFIX + content_hash(text)
        await redis.set(key, json.dumps(vector), ex=EMBED_CACHE_TTL)
    except Exception:
        pass


async def get_cached_parse(doc_hash: str) -> list[dict] | None:
    try:
        redis = await get_redis()
        key = PARSE_CACHE_PREFIX + doc_hash
        raw = await redis.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


async def set_cached_parse(doc_hash: str, chunks: list[dict]) -> None:
    try:
        redis = await get_redis()
        key = PARSE_CACHE_PREFIX + doc_hash
        await redis.set(key, json.dumps(chunks), ex=EMBED_CACHE_TTL)
    except Exception:
        pass


async def get_progress(job_id: str) -> dict | None:
    try:
        redis = await get_redis()
        key = PROGRESS_PREFIX + job_id
        raw = await redis.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


async def set_progress(job_id: str, progress: int, stage: str) -> None:
    try:
        redis = await get_redis()
        key = PROGRESS_PREFIX + job_id
        await redis.set(key, json.dumps({"progress": progress, "stage": stage}), ex=3600)
    except Exception:
        pass
