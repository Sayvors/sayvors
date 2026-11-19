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


def _embedding_cache_key(text: str, model: str | None) -> str:
    """Model is part of the key: a vector from provider A is not comparable
    with chunks embedded by B, and hybrid_search excludes chunks by model tag.
    A model-blind cache would silently return zero results after a switch."""
    return EMBED_CACHE_PREFIX + content_hash(f"{model or ''}\x00{text}")


async def get_cached_embedding(text: str, *, model: str | None = None) -> list[float] | None:
    try:
        redis = await get_redis()
        raw = await redis.get(_embedding_cache_key(text, model))
        if raw:
            vector = json.loads(raw)
            if (
                isinstance(vector, list)
                and vector
                and all(isinstance(v, (int, float)) for v in vector)
            ):
                return vector
            # A corrupt entry must not poison retrieval: treat it as a miss.
            await redis.delete(_embedding_cache_key(text, model))
    except Exception:
        pass
    return None


async def set_cached_embedding(
    text: str, vector: list[float], *, model: str | None = None
) -> None:
    try:
        redis = await get_redis()
        await redis.set(
            _embedding_cache_key(text, model),
            json.dumps(vector),
            ex=EMBED_CACHE_TTL,
        )
    except Exception:
        pass


async def note_embed_cache_result(*, hit: bool) -> None:
    """Count cache hits/misses so the saving is measurable (purpose rag.embed)."""
    try:
        redis = await get_redis()
        await redis.incr(EMBED_CACHE_PREFIX + ("hits" if hit else "misses"))
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
