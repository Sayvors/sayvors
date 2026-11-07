"""Short-lived Ask Sayvors conversation memory.

The browser already persists chats in localStorage. This store gives the
server the same context so a follow-up ("show that by location", "make it a
pie") can reuse the previous dataset instead of querying again or inventing
new numbers.

Redis is the shared store (multi-worker safe), with a bounded in-process
fallback so a Redis outage only loses cross-worker continuity, never the
current reply.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

TTL_SECONDS = 24 * 60 * 60
MAX_TURNS = 20
MAX_DATASETS = 8
MAX_CHARTS = 12
MAX_DATASET_ROWS = 120
MAX_SERIALIZED_CHARS = 220_000
RECALL_SECONDS = 15 * 60

_fallback: dict[str, tuple[float, dict]] = {}
_FALLBACK_MAX = 256


def empty_memory() -> dict:
    return {"turns": [], "datasets": {}, "charts": []}


def _key(tenant_id: str, session_id: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{session_id}".encode("utf-8")).hexdigest()[:40]
    return f"assistant:session:{digest}"


def _normalize(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return empty_memory()
    turns = [
        {"role": str(t.get("role")), "content": str(t.get("content") or "")[:4000]}
        for t in raw.get("turns", [])
        if isinstance(t, dict) and t.get("role") in ("user", "assistant")
    ][-MAX_TURNS:]
    datasets = {
        str(k): v
        for k, v in (raw.get("datasets") or {}).items()
        if isinstance(v, dict) and v.get("rows")
    }
    charts = [
        c for c in (raw.get("charts") or [])
        if isinstance(c, dict) and c.get("title")
    ][-MAX_CHARTS:]
    return {"turns": turns, "datasets": datasets, "charts": charts}


async def load_memory(tenant_id: str, session_id: str | None) -> dict:
    if not session_id:
        return empty_memory()
    key = _key(tenant_id, session_id)
    try:
        from ..redis.client import get_redis

        raw = await (await get_redis()).get(key)
        if raw:
            return _normalize(json.loads(raw))
    except Exception as e:
        logger.debug("assistant memory read failed: %s", e)
    hit = _fallback.get(key)
    if hit and time.time() - hit[0] < TTL_SECONDS:
        return _normalize(hit[1])
    return empty_memory()


async def save_memory(tenant_id: str, session_id: str | None, memory: dict) -> None:
    if not session_id:
        return
    data = _prune(memory)
    key = _key(tenant_id, session_id)
    payload = json.dumps(data, ensure_ascii=False, default=str)
    if len(payload) > MAX_SERIALIZED_CHARS:
        data = _prune(data, aggressive=True)
        payload = json.dumps(data, ensure_ascii=False, default=str)
    try:
        from ..redis.client import get_redis

        await (await get_redis()).set(key, payload, ex=TTL_SECONDS)
        return
    except Exception as e:
        logger.debug("assistant memory write failed: %s", e)
    if len(_fallback) >= _FALLBACK_MAX:
        oldest = min(_fallback, key=lambda k: _fallback[k][0])
        _fallback.pop(oldest, None)
    _fallback[key] = (time.time(), data)


def _prune(memory: dict, aggressive: bool = False) -> dict:
    turns = list(memory.get("turns") or [])[-MAX_TURNS:]
    charts = list(memory.get("charts") or [])[-MAX_CHARTS:]
    datasets = dict(memory.get("datasets") or {})
    if len(datasets) > MAX_DATASETS:
        ordered = sorted(
            datasets.items(),
            key=lambda item: float(item[1].get("created_at") or 0),
            reverse=True,
        )[:MAX_DATASETS]
        datasets = dict(ordered)
    # Rows are aggregates, but an aggressive prune still keeps memory bounded
    # for a chat that asks many follow-up questions on wide datasets.
    row_cap = 40 if aggressive else MAX_DATASET_ROWS
    cleaned: dict[str, dict] = {}
    for key, value in datasets.items():
        if not isinstance(value, dict):
            continue
        rows = value.get("rows")
        if not isinstance(rows, list) or not rows:
            continue
        cleaned[key] = {**value, "rows": rows[:row_cap]}
    return {"turns": turns, "datasets": cleaned, "charts": charts}


def append_turn(memory: dict, role: str, content: str) -> None:
    text = (content or "").strip()
    if not text:
        return
    memory.setdefault("turns", []).append({"role": role, "content": text[:4000]})
    memory["turns"] = memory["turns"][-MAX_TURNS:]


def remember_dataset(memory: dict, dataset: dict) -> None:
    dataset_id = dataset.get("dataset_id")
    if not dataset_id:
        return
    record = {
        **dataset,
        "rows": list(dataset.get("rows") or [])[:MAX_DATASET_ROWS],
        "created_at": time.time(),
    }
    memory.setdefault("datasets", {})[dataset_id] = record
    if len(memory["datasets"]) > MAX_DATASETS:
        oldest = min(
            memory["datasets"],
            key=lambda k: float(memory["datasets"][k].get("created_at") or 0),
        )
        memory["datasets"].pop(oldest, None)


def recall_dataset(memory: dict, query_key: str) -> dict | None:
    now = time.time()
    hits = [
        d for d in (memory.get("datasets") or {}).values()
        if d.get("query_key") == query_key
        and now - float(d.get("created_at") or 0) <= RECALL_SECONDS
    ]
    if not hits:
        return None
    return max(hits, key=lambda d: float(d.get("created_at") or 0))


def remember_chart(memory: dict, chart: dict) -> None:
    memory.setdefault("charts", []).append({
        "title": chart.get("title"),
        "type": chart.get("type"),
        "dataset": chart.get("dataset"),
        "signature": chart.get("signature"),
        "created_at": time.time(),
    })
    memory["charts"] = memory["charts"][-MAX_CHARTS:]


def chart_signatures(memory: dict) -> set[str]:
    return {
        str(c.get("signature"))
        for c in (memory.get("charts") or [])
        if c.get("signature")
    }


def dataset_summaries(memory: dict) -> list[dict]:
    """Compact list for the planner prompt; rows stay on the server."""
    out = []
    now = time.time()
    for dataset in (memory.get("datasets") or {}).values():
        if now - float(dataset.get("created_at") or 0) > RECALL_SECONDS:
            continue
        out.append({
            "dataset_id": dataset.get("dataset_id"),
            "dataset": dataset.get("dataset"),
            "title": dataset.get("title"),
            "query_key": dataset.get("query_key"),
            "columns": dataset.get("columns"),
            "row_count": len(dataset.get("rows") or []),
            "suggested_type": dataset.get("suggested_type"),
            "suggested_series": dataset.get("suggested_series"),
        })
    return out[-MAX_DATASETS:]
