"""Platform overview + tenant queries. Read-only by design (v1)."""
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import ReviewInsight
from ..channels.models import ReviewReply
from ..localith.models import LocalithConnection
from ..media.models import LocationMedia
from ..outbox.models import EventOutbox
from ..posts.models import LocationPost
from ..rag.models import Databank, Document
from ..rag.models import IngestJob
from ..users.models import User

logger = logging.getLogger(__name__)

_booted_at = datetime.now(timezone.utc)


async def _counts_by_user(db: AsyncSession, model, user_col="user_id") -> dict[str, int]:
    rows = (
        await db.execute(
            select(getattr(model, user_col), func.count()).group_by(getattr(model, user_col))
        )
    ).all()
    return {str(uid): int(n) for uid, n in rows}


async def get_overview(db: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    users_total = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    users_verified = (
        await db.execute(select(func.count()).select_from(User).where(User.email_verified == True))  # noqa: E712
    ).scalar() or 0
    signups = (
        await db.execute(
            select(func.count()).select_from(User).where(User.created_at >= now - timedelta(days=7))
        )
    ).scalar() or 0
    connections = (
        await db.execute(select(func.count()).select_from(LocalithConnection))
    ).scalar() or 0
    last_sync = (
        await db.execute(select(func.max(LocalithConnection.last_synced_at)))
    ).scalar()
    reviews = (
        await db.execute(select(func.count()).select_from(ReviewInsight))
    ).scalar() or 0
    post_rows = (
        await db.execute(select(LocationPost.status, func.count()).group_by(LocationPost.status))
    ).all()
    posts_by_status = {str(s): int(n) for s, n in post_rows}
    reply_rows = (
        await db.execute(select(ReviewReply.status, func.count()).group_by(ReviewReply.status))
    ).all()
    replies_by_status = {str(s): int(n) for s, n in reply_rows}
    media_rows = (
        await db.execute(select(LocationMedia.status, func.count()).group_by(LocationMedia.status))
    ).all()
    media_by_status = {str(s): int(n) for s, n in media_rows}
    databanks = (
        await db.execute(select(func.count()).select_from(Databank))
    ).scalar() or 0
    documents = (
        await db.execute(select(func.count()).select_from(Document))
    ).scalar() or 0
    outbox_pending = (
        await db.execute(
            select(func.count()).select_from(EventOutbox).where(EventOutbox.status == "pending")
        )
    ).scalar() or 0
    outbox_failed = (
        await db.execute(
            select(func.count()).select_from(EventOutbox).where(EventOutbox.status == "failed")
        )
    ).scalar() or 0
    ingest_failed = (
        await db.execute(
            select(func.count()).select_from(IngestJob).where(IngestJob.status == "failed")
        )
    ).scalar() or 0
    return {
        "users_total": users_total,
        "users_verified": users_verified,
        "signups_last_7d": signups,
        "connections": connections,
        "last_synced_at": last_sync.isoformat() if last_sync else None,
        "reviews_total": reviews,
        "posts_total": sum(posts_by_status.values()),
        "posts_by_status": posts_by_status,
        "replies_by_status": replies_by_status,
        "media_by_status": media_by_status,
        "databanks_total": databanks,
        "documents_total": documents,
        "outbox_pending": outbox_pending,
        "outbox_failed": outbox_failed,
        "ingest_failed": ingest_failed,
    }


async def list_tenants(
    db: AsyncSession, search: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    filters = []
    if search:
        like = f"%{search.lower()}%"
        filters.append(
            or_(
                func.lower(User.email).like(like),
                func.lower(func.coalesce(User.first_name, "")).like(like),
                func.lower(func.coalesce(User.last_name, "")).like(like),
            )
        )
    total = (
        await db.execute(select(func.count()).select_from(User).where(*filters))
    ).scalar() or 0
    users = (
        await db.execute(
            select(User).where(*filters).order_by(User.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    if not users:
        return [], total

    ids = [u.id for u in users]
    conns = (
        await db.execute(select(LocalithConnection).where(LocalithConnection.user_id.in_(ids)))
    ).scalars().all()
    conn_by_user: dict[str, list] = {}
    for c in conns:
        conn_by_user.setdefault(c.user_id, []).append(c)
    review_counts = await _counts_by_user(db, ReviewInsight)
    post_counts = await _counts_by_user(db, LocationPost)
    bank_counts = await _counts_by_user(db, Databank)

    items = []
    for u in users:
        user_conns = conn_by_user.get(u.id, [])
        c = user_conns[0] if user_conns else None
        items.append({
            "id": u.id,
            "email": u.email,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "email_verified": bool(u.email_verified),
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "has_connection": c is not None,
            "listing_name": c.listing_name if c else None,
            "listings_count": len(user_conns),
            "last_synced_at": c.last_synced_at.isoformat() if c and c.last_synced_at else None,
            "reviews": review_counts.get(u.id, 0),
            "posts": post_counts.get(u.id, 0),
            "databanks": bank_counts.get(u.id, 0),
            "plan": u.plan or "free",
            "ai_credit_cents": u.ai_credit_cents or 0,
        })
    return items, total


async def get_tenant(db: AsyncSession, user_id: str) -> dict | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    conn = (
        await db.execute(
            select(LocalithConnection)
            .where(LocalithConnection.user_id == user_id)
            .order_by(LocalithConnection.created_at)
        )
    ).scalars().first()
    review_counts = await _counts_by_user(db, ReviewInsight)
    post_counts = await _counts_by_user(db, LocationPost)
    bank_counts = await _counts_by_user(db, Databank)
    base = {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email_verified": bool(user.email_verified),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "has_connection": conn is not None,
        "listing_name": conn.listing_name if conn else None,
        "last_synced_at": conn.last_synced_at.isoformat() if conn and conn.last_synced_at else None,
        "reviews": review_counts.get(user.id, 0),
        "posts": post_counts.get(user.id, 0),
        "databanks": bank_counts.get(user.id, 0),
        "plan": user.plan or "free",
        "ai_credit_cents": user.ai_credit_cents or 0,
    }
    recent_reviews = (
        await db.execute(
            select(ReviewInsight)
            .where(ReviewInsight.user_id == user_id)
            .order_by(ReviewInsight.created_at.desc())
            .limit(5)
        )
    ).scalars().all()
    base["recent_reviews"] = [
        {
            "id": r.id, "rating": r.rating,
            "text": (r.review_text or "")[:160],
            "reviewer": r.reviewer_name, "sentiment": r.sentiment,
            "replied": r.replied,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent_reviews
    ]
    recent_posts = (
        await db.execute(
            select(LocationPost)
            .where(LocationPost.user_id == user_id)
            .order_by(LocationPost.created_at.desc())
            .limit(5)
        )
    ).scalars().all()
    base["recent_posts"] = [
        {
            "id": p.id, "title": p.title, "status": p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in recent_posts
    ]
    # AI wallet: live Redis balance + estimated 30d spend (upper bound —
    # by_model rows carry totals only, priced at the completion rate).
    from ..billing.budget import TOKEN_PRICES, get_balance

    base["ai_balance_cents"] = await get_balance(user_id)
    try:
        from ..llm.usage import get_tenant_summary

        summary = await get_tenant_summary(db, user_id, 30)
        spent = 0
        for row in summary.get("by_model", []):
            fam = (row.get("model") or "").split(":", 1)[0].lower() or "unknown"
            _, completion_p = TOKEN_PRICES.get(fam, TOKEN_PRICES["unknown"])
            spent += (row.get("total_tokens", 0) / 1_000_000) * completion_p
        import math

        base["ai_spent_30d_cents"] = math.ceil(spent)
    except Exception:
        base["ai_spent_30d_cents"] = 0
    return base


# ── Service health (for the admin Logs page) ────────────────────

def _timed(coro_or_value):
    """Run a check, returning (ok, latency_ms, detail). Never raises."""
    import asyncio

    async def _run():
        start = time.monotonic()
        try:
            if asyncio.iscoroutine(coro_or_value):
                detail = await coro_or_value
            else:
                detail = coro_or_value
            return True, round((time.monotonic() - start) * 1000), detail
        except Exception as e:
            return False, round((time.monotonic() - start) * 1000), f"{type(e).__name__}: {str(e)[:160]}"

    return _run()


async def _check_database(db: AsyncSession) -> str:
    await db.execute(text("SELECT 1"))
    return "PostgreSQL reachable"


async def _check_redis() -> str:
    from ..redis.client import get_redis

    client = await get_redis()
    await client.ping()
    return "Redis PONG"


async def _check_kafka() -> str:
    from ..kafka import client as kafka_client

    if not kafka_client._kafka_available:
        raise RuntimeError("producer not connected (outbox fallback active)")
    return "producer connected"


_PROBE_URLS = {    "groq": "https://api.groq.com/openai/v1/models",
    "openai": "https://api.openai.com/v1/models",
    "grok": "https://api.x.ai/v1/models",
    "kimi": "https://api.moonshot.cn/v1/models",
    "deepseek": "https://api.deepseek.com/v1/models",
    "gemini": "gemini",
    "ollama": "http://localhost:11434/api/tags",
}


def _ai_providers_configured(db_rows: dict[str, dict]) -> list[dict]:
    from app.modules.llm.providers.catalog import PROVIDERS

    out = []
    for name in PROVIDERS:
        entry = db_rows.get(name)
        if entry is None:
            out.append({"name": name, "configured": False, "url": _PROBE_URLS[name],
                        "enabled": True, "source": "none"})
        else:
            enabled = bool(entry.get("enabled", True))
            has_key = bool(entry.get("key_encrypted"))
            out.append({
                "name": name,
                "configured": has_key and enabled,
                "url": _PROBE_URLS[name],
                "enabled": enabled,
                "source": "disabled" if not enabled else ("database" if has_key else "none"),
            })
    return out


async def _probe_ai_provider(name: str, url: str, timeout: int = 10) -> str:
    """Free liveness probe (model list, no tokens spent). DB-resolved key."""
    import httpx

    from ..llm.providers.registry import resolve_provider_key

    key, _source = resolve_provider_key(name)
    if name == "gemini":
        resp = httpx.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key or ""},
            timeout=timeout,
        )
    elif name == "ollama":
        resp = httpx.get(url, timeout=timeout)
    else:
        resp = httpx.get(
            url, headers={"Authorization": f"Bearer {key or ''}"}, timeout=timeout
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}")
    data = resp.json()
    models = None
    if isinstance(data, dict):
        # OpenAI-compatible: {"data": [...]}, Gemini/Ollama: {"models": [...]}.
        for key in ("data", "models"):
            if isinstance(data.get(key), list):
                models = data[key]
                break
    n = len(models) if isinstance(models, list) else "?"
    return f"reachable ({n} models listed)"


async def _check_localith(probe: bool) -> str:
    from ...config import settings

    if not settings.LOCALITH_API_KEY:
        raise RuntimeError("LOCALITH_API_KEY not set")
    if not probe:
        return "API key configured"
    import asyncio as _asyncio

    from integrations.channels import embedsocial

    listings = await _asyncio.to_thread(embedsocial.fetch_listings)
    return f"reachable ({len(listings)} listing(s))"


async def _provider_rows(db: AsyncSession) -> dict[str, dict]:
    from app.modules.llm.models import ProviderConfig

    rows = (await db.execute(select(ProviderConfig))).scalars().all()
    return {
        r.provider: {"key_encrypted": r.key_encrypted, "enabled": r.enabled}
        for r in rows
    }


async def get_health(db: AsyncSession, probe: bool = False) -> dict:
    """Per-service status + recent failures. probe=True does live checks."""
    services: list[dict] = []

    ok, ms, detail = await _timed(_check_database(db))
    services.append({"name": "Database", "kind": "postgres", "ok": ok, "latency_ms": ms, "detail": detail})

    ok, ms, detail = await _timed(_check_redis())
    services.append({
        "name": "Redis", "kind": "cache/ratelimit", "ok": ok, "latency_ms": ms,
        "detail": detail if ok else detail + " (auth runs fail-open ONLY if configured)",
    })

    ok, ms, detail = await _timed(_check_kafka())
    services.append({"name": "Kafka", "kind": "events", "ok": ok, "latency_ms": ms, "detail": detail})

    ok, ms, detail = await _timed(_check_localith(probe))
    services.append({"name": "Localith", "kind": "business-data", "ok": ok, "latency_ms": ms, "detail": detail})

    db_rows = await _provider_rows(db)
    for provider in _ai_providers_configured(db_rows):
        # Only show providers with a key stored in DB — hide "missing key" / "disabled" (not ready for tenants)
        if provider["source"] != "database":
            continue
        if not provider["configured"]:
            reason = "disabled by admin" if provider["source"] == "disabled" else "no API key configured"
            services.append({
                "name": f"AI:{provider['name']}", "kind": "llm",
                "ok": False, "latency_ms": 0, "detail": reason,
                "enabled": provider["enabled"], "key_source": provider["source"],
            })
            continue
        if not probe:
            services.append({
                "name": f"AI:{provider['name']}", "kind": "llm",
                "ok": True, "latency_ms": 0, "detail": "key configured (live check not run)",
                "enabled": True, "key_source": provider["source"],
            })
            continue
        ok, ms, detail = await _timed(_probe_ai_provider(provider["name"], provider["url"]))
        services.append({
            "name": f"AI:{provider['name']}", "kind": "llm",
            "ok": ok, "latency_ms": ms, "detail": detail,
            "enabled": True, "key_source": provider["source"],
        })

    failed_outbox = (
        await db.execute(
            select(EventOutbox)
            .where(EventOutbox.status.in_(["failed", "dead"]))
            .order_by(EventOutbox.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    failed_ingest = (
        await db.execute(
            select(IngestJob)
            .where(IngestJob.status == "failed")
            .order_by(IngestJob.updated_at.desc())
            .limit(10)
        )
    ).scalars().all()
    failures = [
        {
            "source": "outbox", "type": v.event_type,
            "message": (v.last_error or v.status or "")[:200],
            "at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in failed_outbox
    ] + [
        {
            "source": "ingest", "type": j.job_type,
            "message": (j.error or "")[:200],
            "at": j.updated_at.isoformat() if j.updated_at else None,
        }
        for j in failed_ingest
    ]

    if any(s["name"] == "Database" and not s["ok"] for s in services):
        overall = "down"
    elif all(s["ok"] for s in services):
        overall = "ok"
    else:
        overall = "degraded"
    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": int((datetime.now(timezone.utc) - _booted_at).total_seconds()),
        "probe": probe,
        "services": services,
        "recent_failures": failures,
    }
