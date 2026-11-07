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


# ── Long-term memory: what the owner asked in previous chats ──────────────
#
# Session memory dies with the chat id. This profile survives it, so a fresh
# chat can still say "last time we looked at the negative reviews" and honor
# an explicit "remember ..." instruction. Bounded and tenant-scoped, never
# shared across businesses.

PROFILE_TTL_SECONDS = 90 * 24 * 60 * 60
PROFILE_MAX_SESSIONS = 8
PROFILE_MAX_NOTES = 20
PROFILE_NOTE_CHARS = 300

_profile_fallback: dict[str, tuple[float, dict]] = {}

_REMEMBER_PATTERNS = (
    "remember that ",
    "remember: ",
    "remember ",
    "don't forget ",
    "do not forget ",
    "احفظ ",
    "تذكر ",
    "تذكّر ",
)


def empty_profile() -> dict:
    return {"sessions": {}, "notes": []}


def _profile_key(tenant_id: str) -> str:
    digest = hashlib.sha256(f"profile:{tenant_id}".encode("utf-8")).hexdigest()[:40]
    return f"assistant:profile:{digest}"


def _normalize_profile(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return empty_profile()
    sessions = {
        str(k): {
            "title": str(v.get("title") or "")[:80],
            "last_user": str(v.get("last_user") or "")[:400],
            "last_answer": str(v.get("last_answer") or "")[:400],
            "turns": int(v.get("turns") or 0),
            "at": float(v.get("at") or 0),
        }
        for k, v in (raw.get("sessions") or {}).items()
        if isinstance(v, dict)
    }
    notes = [str(n)[:PROFILE_NOTE_CHARS] for n in (raw.get("notes") or []) if n][-PROFILE_MAX_NOTES:]
    return {"sessions": sessions, "notes": notes}


async def load_profile(tenant_id: str) -> dict:
    key = _profile_key(tenant_id)
    try:
        from ..redis.client import get_redis

        raw = await (await get_redis()).get(key)
        if raw:
            return _normalize_profile(json.loads(raw))
    except Exception as e:
        logger.debug("assistant profile read failed: %s", e)
    hit = _profile_fallback.get(key)
    if hit and time.time() - hit[0] < PROFILE_TTL_SECONDS:
        return _normalize_profile(hit[1])
    return empty_profile()


async def save_profile(tenant_id: str, profile: dict) -> None:
    data = _prune_profile(profile)
    key = _profile_key(tenant_id)
    payload = json.dumps(data, ensure_ascii=False, default=str)
    try:
        from ..redis.client import get_redis

        await (await get_redis()).set(key, payload, ex=PROFILE_TTL_SECONDS)
        return
    except Exception as e:
        logger.debug("assistant profile write failed: %s", e)
    if len(_profile_fallback) >= _FALLBACK_MAX:
        oldest = min(_profile_fallback, key=lambda k: _profile_fallback[k][0])
        _profile_fallback.pop(oldest, None)
    _profile_fallback[key] = (time.time(), data)


async def forget_profile(tenant_id: str) -> None:
    """Delete the long-term memory for a tenant (admin purge)."""
    key = _profile_key(tenant_id)
    _profile_fallback.pop(key, None)
    try:
        from ..redis.client import get_redis

        await (await get_redis()).delete(key)
    except Exception as e:
        logger.debug("assistant profile delete failed: %s", e)


def _prune_profile(profile: dict) -> dict:
    sessions = dict(profile.get("sessions") or {})
    if len(sessions) > PROFILE_MAX_SESSIONS:
        newest = sorted(sessions.items(), key=lambda item: float(item[1].get("at") or 0), reverse=True)
        sessions = dict(newest[:PROFILE_MAX_SESSIONS])
    notes = [str(n)[:PROFILE_NOTE_CHARS] for n in (profile.get("notes") or [])][-PROFILE_MAX_NOTES:]
    return {"sessions": sessions, "notes": notes}


def _note_from_message(text: str) -> str | None:
    lowered = (text or "").lower()
    for marker in _REMEMBER_PATTERNS:
        index = lowered.find(marker)
        if index >= 0:
            note = " ".join(text[index + len(marker):].split())
            return note[:PROFILE_NOTE_CHARS] or None
    return None


async def remember_session(
    tenant_id: str,
    session_id: str | None,
    user_text: str,
    assistant_text: str | None,
) -> None:
    """Record the last exchange of a chat so other chats can reference it."""
    if not session_id:
        return
    profile = await load_profile(tenant_id)
    sessions = profile.setdefault("sessions", {})
    previous = sessions.get(session_id) or {}
    answer = (assistant_text or "").strip()
    sessions[session_id] = {
        "title": previous.get("title") or (user_text or "").strip()[:80],
        "last_user": (user_text or "").strip()[:400],
        "last_answer": answer[:400],
        "turns": int(previous.get("turns") or 0) + 1,
        "at": time.time(),
    }
    note = _note_from_message(user_text)
    if note:
        notes = profile.setdefault("notes", [])
        if note not in notes:
            notes.append(note)
    await save_profile(tenant_id, profile)


def profile_prompt_block(profile: dict, exclude_session: str | None = None) -> str:
    """Prior-chat context + owner notes, or "" when there is nothing to say."""
    sessions = [
        (sid, item)
        for sid, item in (profile.get("sessions") or {}).items()
        if sid != exclude_session
    ]
    sessions.sort(key=lambda item: float(item[1].get("at") or 0), reverse=True)
    notes = list(profile.get("notes") or [])

    lines: list[str] = []
    for _, item in sessions[:6]:
        title = item.get("title") or "Earlier chat"
        last_user = (item.get("last_user") or "").strip()
        last_answer = (item.get("last_answer") or "").strip()
        line = f'- "{title}"'
        if last_user:
            line += f': the owner last asked "{last_user[:160]}"'
        if last_answer:
            line += f'; you answered "{last_answer[:160]}"'
        lines.append(line)
    block = ""
    if lines:
        block += (
            "\n\nCONVERSATION MEMORY (previous chats with this owner, persisted "
            "across sessions — use it only when relevant, never recite it "
            "unprompted):\n" + "\n".join(lines)
        )
    if notes:
        block += (
            "\n\nOWNER NOTES (things the owner explicitly asked you to remember):\n"
            + "\n".join(f"- {note}" for note in notes[-10:])
        )
    return block
