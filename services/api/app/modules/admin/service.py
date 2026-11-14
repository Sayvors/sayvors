"""Platform overview + tenant queries. Read-only by design (v1)."""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import ReviewInsight
from ..channels.models import Channel, ReviewReply
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


def _last_sync(channel: Channel) -> str | None:
    """Last successful Google sync, or the channel row's last update."""
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except (TypeError, ValueError):
        meta = {}
    health = meta.get("health") if isinstance(meta, dict) else {}
    value = (health or {}).get("last_success_at") if isinstance(health, dict) else None
    if value:
        return str(value)
    return channel.updated_at.isoformat() if channel.updated_at else None


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
    google_channels = (
        await db.execute(
            select(Channel).where(Channel.platform == "google_reviews")
        )
    ).scalars().all()
    connections = len({c.user_id for c in google_channels})
    last_sync = max(
        (_last_sync(c) for c in google_channels if _last_sync(c)),
        default=None,
    )
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
        "last_synced_at": last_sync,
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
        await db.execute(
            select(Channel).where(
                Channel.user_id.in_(ids),
                Channel.platform == "google_reviews",
                Channel.status != "disconnected",
            )
        )
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
            "listing_name": c.display_name if c else None,
            "listings_count": len(user_conns),
            "last_synced_at": _last_sync(c) if c else None,
            "reviews": review_counts.get(u.id, 0),
            "posts": post_counts.get(u.id, 0),
            "databanks": bank_counts.get(u.id, 0),
            "plan": u.plan or "free",
            "ai_credit_cents": u.ai_credit_cents or 0,
            "suspended_at": u.suspended_at.isoformat() if u.suspended_at else None,
            "suspension_reason": u.suspension_reason,
        })
    return items, total


async def get_tenant(db: AsyncSession, user_id: str) -> dict | None:
    user = await db.get(User, user_id)
    if user is None:
        return None
    conns = (
        await db.execute(
            select(Channel)
            .where(
                Channel.user_id == user_id,
                Channel.platform == "google_reviews",
                Channel.status != "disconnected",
            )
            .order_by(Channel.created_at)
        )
    ).scalars().all()
    conn = conns[0] if conns else None
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
        "listing_name": conn.display_name if conn else None,
        "last_synced_at": _last_sync(conn) if conn else None,
        "reviews": review_counts.get(user.id, 0),
        "posts": post_counts.get(user.id, 0),
        "databanks": bank_counts.get(user.id, 0),
        "plan": user.plan or "free",
        "ai_credit_cents": user.ai_credit_cents or 0,
        "suspended_at": user.suspended_at.isoformat() if user.suspended_at else None,
        "suspension_reason": user.suspension_reason,
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
    # AI wallet: durable DB balance + estimated 30d spend (upper bound —
    # by_model rows carry totals only, priced at the completion rate).
    from ..billing.budget import TOKEN_PRICES, get_balance

    base["ai_balance_cents"] = await get_balance(user_id)
    # Keep the detail payload consistent with the authoritative wallet even
    # for a tenant whose column has not been cut over yet.
    if base["ai_balance_cents"] is not None:
        base["ai_credit_cents"] = base["ai_balance_cents"]
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

    if not kafka_client.is_kafka_available():
        raise RuntimeError("producer not connected (outbox fallback active)")
    return "producer connected"


_PROBE_URLS = {
    "groq": "https://api.groq.com/openai/v1/models",
    "openai": "https://api.openai.com/v1/models",
    "grok": "https://api.x.ai/v1/models",
    "kimi": "https://api.moonshot.cn/v1/models",
    "deepseek": "https://api.deepseek.com/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "zhipu": "https://api.z.ai/api/paas/v4/models",
    "zhipu-coding": "https://api.z.ai/api/coding/paas/v4/models",
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


async def list_budget_alarms(
    db: AsyncSession,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Tenants with a non-healthy AI-credit balance (low/empty/debt).

    Same status classification as the billing overview so the two views
    never disagree. Sorted worst-first (lowest balance). Bounded and
    paginated.
    """
    from sqlalchemy import func, select as _select

    from ..billing.models import BillingEvent, Plan, TenantSubscription
    from ..users.models import User

    held_sub = (
        _select(
            BillingEvent.tenant_id,
            func.coalesce(func.sum(BillingEvent.reserved_cents), 0).label("held"),
        )
        .where(BillingEvent.kind == "ai_usage", BillingEvent.status == "pending")
        .group_by(BillingEvent.tenant_id)
        .subquery()
    )
    plan_sub = (
        _select(
            TenantSubscription.tenant_id,
            Plan.slug.label("plan_slug"),
            Plan.name.label("plan_name"),
        )
        .join(Plan, Plan.id == TenantSubscription.plan_id)
        .subquery()
    )
    base = (
        _select(
            User.id,
            User.email,
            User.ai_credit_cents,
            func.coalesce(held_sub.c.held, 0).label("held_cents"),
            func.coalesce(plan_sub.c.plan_slug, "free-trial").label("plan_slug"),
            func.coalesce(plan_sub.c.plan_name, "Free Trial").label("plan_name"),
        )
        .outerjoin(held_sub, held_sub.c.tenant_id == User.id)
        .outerjoin(plan_sub, plan_sub.c.tenant_id == User.id)
    )
    rows = (await db.execute(base.order_by(User.ai_credit_cents.asc(), User.email))).all()

    items = []
    for uid, email, balance, held, plan_slug, plan_name in rows:
        balance = int(balance or 0)
        held = int(held or 0)
        if balance < 0:
            s = "debt"
        elif balance == 0:
            s = "empty"
        elif balance < 100:
            s = "low"
        else:
            continue
        if status and s != status:
            continue
        items.append({
            "tenant_id": uid,
            "email": email,
            "plan_slug": plan_slug,
            "plan_name": plan_name,
            "balance_cents": balance,
            "held_cents": held,
            "total_cents": balance + held,
            "status": s,
        })

    total = len(items)
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    return {"items": items[offset:offset + limit], "total": total}


async def admin_search(
    db: AsyncSession,
    query: str,
    *,
    limit: int = 8,
) -> dict:
    """Metadata-only admin search across tenants, operators, models, plans,
    jobs and audit log. Never searches message/review bodies or secrets."""
    from sqlalchemy import cast as sa_cast, or_, select as _select
    from sqlalchemy import String as sa_String

    from ..billing.models import Plan
    from ..jobs.models import Job
    from ..llm.models import ModelConfig, ProviderConfig
    from ..users.models import User
    from .models import AdminAuditLog, PlatformOperator

    q = query.strip()
    if len(q) < 2:
        return {"query": query, "groups": [], "total": 0}
    needle = f"%{q}%"
    limit = max(1, min(int(limit), 25))
    groups: list[dict] = []

    def add(group: str, label: str, items: list[dict]) -> None:
        if items:
            groups.append({"key": group, "label": label, "items": items})

    # Tenants
    tenants = (
        await db.execute(
            _select(User)
            .where(or_(
                User.email.ilike(needle),
                User.first_name.ilike(needle),
                User.last_name.ilike(needle),
                User.id.ilike(needle),
            ))
            .order_by(User.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    add("tenants", "Tenants", [{
        "id": u.id,
        "group": "tenants",
        "title": f"{u.first_name or ''} {u.last_name or ''}".strip() or u.email,
        "subtitle": f"{u.email} · {u.id}",
        "href": f"/tenants/{u.id}",
        "meta": "tenant",
    } for u in tenants])

    # Operators
    operators = (
        await db.execute(
            _select(PlatformOperator)
            .where(or_(PlatformOperator.username.ilike(needle), PlatformOperator.role.ilike(needle)))
            .order_by(PlatformOperator.username)
            .limit(limit)
        )
    ).scalars().all()
    add("operators", "Operators", [{
        "id": op.id,
        "group": "operators",
        "title": op.username,
        "subtitle": f"{op.role} · {'active' if op.is_active else 'disabled'}",
        "href": "/operators",
        "meta": op.role,
    } for op in operators])

    # Models (custom configs + provider rows)
    models = (
        await db.execute(
            _select(ModelConfig)
            .where(or_(
                ModelConfig.model_id.ilike(needle),
                ModelConfig.provider.ilike(needle),
                ModelConfig.api_model.ilike(needle),
                ModelConfig.display_name.ilike(needle),
            ))
            .order_by(ModelConfig.model_id)
            .limit(limit)
        )
    ).scalars().all()
    add("models", "Models", [{
        "id": m.model_id,
        "group": "models",
        "title": m.model_id,
        "subtitle": f"{m.provider or 'catalog'} · {m.api_model or ''}".strip(" ·"),
        "href": "/llms",
        "meta": "LLM",
    } for m in models])
    providers = (
        await db.execute(
            _select(ProviderConfig).where(ProviderConfig.provider.ilike(needle)).limit(limit)
        )
    ).scalars().all()
    for p in providers:
        groups_match = next((g for g in groups if g["key"] == "models"), None)
        if groups_match is None:
            groups.append({"key": "models", "label": "Models", "items": []})
            groups_match = groups[-1]
        groups_match["items"].append({
            "id": p.provider,
            "group": "models",
            "title": p.provider,
            "subtitle": f"provider key · {'enabled' if p.enabled else 'disabled'}",
            "href": "/llms",
            "meta": "provider",
        })

    # Plans
    plans = (
        await db.execute(
            _select(Plan)
            .where(or_(Plan.name.ilike(needle), Plan.slug.ilike(needle)))
            .order_by(Plan.sort_order)
            .limit(limit)
        )
    ).scalars().all()
    add("plans", "Plans", [{
        "id": p.slug,
        "group": "plans",
        "title": p.name,
        "subtitle": p.description or p.slug,
        "href": "/plans",
        "meta": p.slug,
    } for p in plans])

    # Jobs (job_type/lane/status are Postgres enums — cast to text before
    # ILIKE, or the operator doesn't exist).
    jobs = (
        await db.execute(
            _select(Job)
            .where(or_(
                sa_cast(Job.job_type, sa_String).ilike(needle),
                sa_cast(Job.lane, sa_String).ilike(needle),
                sa_cast(Job.status, sa_String).ilike(needle),
                Job.tenant_id.ilike(needle),
            ))
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    add("jobs", "Jobs", [{
        "id": j.id,
        "group": "jobs",
        "title": j.job_type,
        "subtitle": f"{j.tenant_id} · {j.status}",
        "href": "/jobs",
        "meta": j.status,
    } for j in jobs])

    # Audit log
    audits = (
        await db.execute(
            _select(AdminAuditLog)
            .where(or_(
                AdminAuditLog.action.ilike(needle),
                AdminAuditLog.operator_username.ilike(needle),
                AdminAuditLog.path.ilike(needle),
                AdminAuditLog.detail.ilike(needle),
            ))
            .order_by(AdminAuditLog.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    add("audit", "Audit log", [{
        "id": a.id,
        "group": "audit",
        "title": a.action,
        "subtitle": f"{a.operator_username or 'system'} · {a.path} · {a.status_code}",
        "href": "/audit-log",
        "meta": a.method,
    } for a in audits])

    total = sum(len(g["items"]) for g in groups)
    return {"query": q, "groups": groups, "total": total}


async def get_billing_overview(db: AsyncSession) -> list[dict]:
    from sqlalchemy import func, select as _select

    from ..billing.models import BillingEvent
    from ..users.models import User

    held_sub = (
        _select(
            BillingEvent.tenant_id,
            func.coalesce(func.sum(BillingEvent.reserved_cents), 0).label("held"),
        )
        .where(BillingEvent.kind == "ai_usage", BillingEvent.status == "pending")
        .group_by(BillingEvent.tenant_id)
        .subquery()
    )
    rows = (
        await db.execute(
            _select(
                User.id,
                User.email,
                User.plan,
                User.ai_credit_cents,
                func.coalesce(held_sub.c.held, 0).label("held_cents"),
            )
            .outerjoin(held_sub, held_sub.c.tenant_id == User.id)
            .order_by(User.ai_credit_cents.asc(), User.email)
        )
    ).all()
    out = []
    for uid, email, plan, balance, held in rows:
        balance = int(balance or 0)
        held = int(held or 0)
        if balance < 0:
            status = "debt"
        elif balance == 0:
            status = "empty"
        elif balance < 100:
            status = "low"
        else:
            status = "ok"
        out.append({
            "tenant_id": uid,
            "email": email,
            "plan": plan or "free",
            "balance_cents": balance,
            "held_cents": held,
            "total_cents": balance + held,
            "status": status,
        })
    return out


async def ensure_finance_rows(db: AsyncSession, month: str) -> int:
    """Upsert monthly finance rows for every tenant with activity in the month.

    Activity = a subscription row OR any metered LLM usage event in that
    month. Auto-fields (plan snapshot, credits used, actual cost) are
    recomputed; admin fields (status/collected/adjustments/note) are kept.
    """
    from datetime import date as _date

    from sqlalchemy import func as _func
    from sqlalchemy import select as _select
    from sqlalchemy.dialects.postgresql import insert as _pg_insert

    import uuid

    from ..billing.models import Plan, TenantFinanceMonth, TenantSubscription
    from ..llm.models import LLMUsageEvent
    from ..users.models import User

    try:
        year, month_num = (int(x) for x in month.split("-", 1))
    except (ValueError, AttributeError):
        raise ValueError("month must be YYYY-MM")
    start = _date(year, month_num, 1)
    if month_num == 12:
        end = _date(year + 1, 1, 1)
    else:
        end = _date(year, month_num + 1, 1)

    tenant_ids = set(
        (
            await db.execute(
                _select(TenantSubscription.tenant_id).where(
                    TenantSubscription.tenant_id.isnot(None)
                )
            )
        ).scalars().all()
    )
    usage_ids = set(
        (
            await db.execute(
                _select(LLMUsageEvent.tenant_id)
                .where(
                    LLMUsageEvent.tenant_id.isnot(None),
                    LLMUsageEvent.created_at >= start,
                    LLMUsageEvent.created_at < end,
                )
                .distinct()
            )
        ).scalars().all()
    )
    for tid in tenant_ids | usage_ids:
        plan = (
            await db.execute(
                _select(Plan)
                .join(TenantSubscription, TenantSubscription.plan_id == Plan.id)
                .where(TenantSubscription.tenant_id == tid)
                .limit(1)
            )
        ).scalar_one_or_none()
        cost_row = (
            await db.execute(
                _select(
                    _func.coalesce(_func.sum(LLMUsageEvent.delivery_cost_micro_usd), 0),
                    _func.coalesce(_func.sum(LLMUsageEvent.cost_cents), 0),
                )
                .where(
                    LLMUsageEvent.tenant_id == tid,
                    LLMUsageEvent.created_at >= start,
                    LLMUsageEvent.created_at < end,
                )
            )
        ).first()
        actual_micro = int(cost_row[0] or 0)
        credits_cents = int(cost_row[1] or 0)
        price_cents = int(plan.price_cents or 0) if plan else 0

        stmt = _pg_insert(TenantFinanceMonth).values(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            month=start,
            plan_slug=plan.slug if plan else None,
            plan_name=plan.name if plan else None,
            plan_price_cents=price_cents,
            credits_used_cents=credits_cents,
            actual_cost_micro=actual_micro,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[TenantFinanceMonth.tenant_id, TenantFinanceMonth.month],
            set_={
                "plan_slug": stmt.excluded.plan_slug,
                "plan_name": stmt.excluded.plan_name,
                "plan_price_cents": stmt.excluded.plan_price_cents,
                "credits_used_cents": stmt.excluded.credits_used_cents,
                "actual_cost_micro": stmt.excluded.actual_cost_micro,
                "updated_at": _func.now(),
            },
        )
        await db.execute(stmt)
    await db.commit()
    return len(tenant_ids | usage_ids)


async def list_financials(
    db: AsyncSession,
    month: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Rows + monthly rollups (expected revenue, collected, infra cost, margin)."""
    from datetime import date as _date

    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    from ..billing.models import TenantFinanceMonth
    from ..users.models import User

    await ensure_finance_rows(db, month)
    year, month_num = (int(x) for x in month.split("-", 1))
    start = _date(year, month_num, 1)

    base = (
        _select(TenantFinanceMonth, User.email)
        .join(User, User.id == TenantFinanceMonth.tenant_id)
        .where(TenantFinanceMonth.month == start)
    )
    rows = (
        await db.execute(
            base.order_by(TenantFinanceMonth.plan_price_cents.desc(), User.email)
            .offset(offset)
            .limit(limit)
        )
    ).all()

    totals = (
        await db.execute(
            _select(
                _func.coalesce(_func.sum(TenantFinanceMonth.plan_price_cents), 0),
                _func.coalesce(_func.sum(TenantFinanceMonth.collected_cents), 0),
                _func.coalesce(_func.sum(TenantFinanceMonth.actual_cost_micro), 0),
            ).where(TenantFinanceMonth.month == start)
        )
    ).first()

    items = []
    for row, email in rows:
        extra = int((row.adjustments or {}).get("extra_cost_cents", 0))
        billed_cents = row.plan_price_cents + extra
        items.append({
            "tenant_id": row.tenant_id,
            "email": email,
            "month": row.month.isoformat(),
            "plan_slug": row.plan_slug,
            "plan_name": row.plan_name,
            "plan_price_cents": row.plan_price_cents,
            "extra_cost_cents": extra,
            "billed_cents": billed_cents,
            "credits_used_cents": row.credits_used_cents,
            "actual_cost_micro": row.actual_cost_micro,
            "collected_cents": row.collected_cents,
            "status": row.status,
            "adjustments": row.adjustments or {},
            "note": row.note,
        })

    expected_cents = int(totals[0] or 0)
    collected_cents = int(totals[1] or 0)
    infra_cost_micro = int(totals[2] or 0)
    return {
        "month": month,
        "items": items,
        "total": len(items),
        "totals": {
            "expected_revenue_cents": expected_cents,
            "collected_cents": collected_cents,
            "infra_cost_micro": infra_cost_micro,
            # column (cents → micro) minus real delivered cost.
            "margin_micro": expected_cents * 10_000 - infra_cost_micro,
            "unpaid_count": 0,
        },
    }


async def patch_finance(
    db: AsyncSession,
    tenant_id: str,
    month: str,
    *,
    status: str | None = None,
    collected_cents: int | None = None,
    adjustments: dict | None = None,
    note: str | None = None,
) -> dict:
    """Admin edit of one monthly row (payment status, collected, notes)."""
    from datetime import date as _date

    from sqlalchemy import select as _select

    from ..billing.models import TenantFinanceMonth

    year, month_num = (int(x) for x in month.split("-", 1))
    start = _date(year, month_num, 1)
    row = (
        await db.execute(
            _select(TenantFinanceMonth).where(
                TenantFinanceMonth.tenant_id == tenant_id,
                TenantFinanceMonth.month == start,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("No finance row for this tenant/month — recompute first.")
    if status is not None:
        if status not in ("unpaid", "paid", "partial"):
            raise ValueError("status must be unpaid, paid or partial")
        row.status = status
    if collected_cents is not None:
        row.collected_cents = max(0, int(collected_cents))
    if adjustments is not None:
        row.adjustments = {k: v for k, v in adjustments.items() if k in ("extra_cost_cents",)}
    if note is not None:
        row.note = note.strip() or None
    await db.commit()
    await db.refresh(row)
    return {
        "tenant_id": row.tenant_id,
        "month": start.isoformat(),
        "status": row.status,
        "collected_cents": row.collected_cents,
        "adjustments": row.adjustments or {},
        "note": row.note,
    }


async def create_admin_notification(
    db: AsyncSession,
    *,
    operator_id: str | None = None,
    kind: str = "system",
    severity: str = "info",
    title: str,
    body: str | None = None,
    href: str | None = None,
) -> None:
    from .models import AdminNotification

    db.add(AdminNotification(
        operator_id=operator_id,
        kind=kind,
        severity=severity,
        title=title[:200],
        body=body,
        href=href,
    ))
    await db.commit()


async def list_admin_notifications(
    db: AsyncSession,
    operator_id: str,
    *,
    unread_only: bool = False,
    limit: int = 50,
) -> dict:
    from sqlalchemy import func as _func, or_, select as _select

    from .models import AdminNotification

    scope = or_(
        AdminNotification.operator_id.is_(None),
        AdminNotification.operator_id == operator_id,
    )
    stmt = _select(AdminNotification).where(scope)
    if unread_only:
        stmt = stmt.where(AdminNotification.read_at.is_(None))
    rows = (
        await db.execute(stmt.order_by(AdminNotification.created_at.desc()).limit(limit))
    ).scalars().all()
    unread = int(
        (
            await db.execute(
                _select(_func.count())
                .select_from(AdminNotification)
                .where(scope, AdminNotification.read_at.is_(None))
            )
        ).scalar_one()
    )
    return {
        "items": [{
            "id": n.id,
            "kind": n.kind,
            "severity": n.severity,
            "title": n.title,
            "body": n.body,
            "href": n.href,
            "read": n.read_at is not None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        } for n in rows],
        "unread_count": unread,
    }


async def mark_admin_notifications_read(
    db: AsyncSession,
    operator_id: str,
    *,
    notification_ids: list[str] | None = None,
) -> int:
    from datetime import datetime, timezone as _tz

    from sqlalchemy import or_, select as _select, update as _update

    from .models import AdminNotification

    scope = or_(
        AdminNotification.operator_id.is_(None),
        AdminNotification.operator_id == operator_id,
    )
    stmt = _update(AdminNotification).where(
        scope, AdminNotification.read_at.is_(None)
    )
    if notification_ids:
        stmt = stmt.where(AdminNotification.id.in_(notification_ids))
    result = await db.execute(stmt.values(read_at=datetime.now(_tz.utc)))
    await db.commit()
    return result.rowcount or 0


LEDGER_SORTS = ("newest", "oldest", "cost_high", "cost_low")
DEFAULT_LEDGER_LIMIT = 75
MAX_LEDGER_LIMIT = 200


async def get_tenant_billing(
    db: AsyncSession,
    user_id: str,
    *,
    include_model: bool = True,
    limit: int = DEFAULT_LEDGER_LIMIT,
    offset: int = 0,
    sort: str = "newest",
) -> dict | None:
    """Tenant billing view. Admin callers keep the model id; tenant callers
    must not see which provider/model the platform uses.

    ``limit``/``offset`` page the ledger rows only; the wallet and pending
    holds are always complete. ``total`` is the full ledger row count so the
    caller can render page controls without a second request.
    """
    from sqlalchemy import case, select as _select

    from ..billing.models import BillingEvent
    from ..llm.models import LLMUsageEvent
    from ..users.models import User

    user = await db.get(User, user_id)
    if user is None:
        return None

    held_rows = (
        await db.execute(
            _select(BillingEvent)
            .where(
                BillingEvent.tenant_id == user_id,
                BillingEvent.kind == "ai_usage",
                BillingEvent.status == "pending",
            )
            .order_by(BillingEvent.created_at.desc())
        )
    ).scalars().all()
    held_cents = int(sum(h.reserved_cents or 0 for h in held_rows))

    limit = max(1, min(int(limit), MAX_LEDGER_LIMIT))
    offset = max(0, int(offset))
    if sort not in LEDGER_SORTS:
        raise ValueError(f"Unsupported ledger sort: {sort}")

    total = int(
        (
            await db.execute(
                _select(func.count())
                .select_from(BillingEvent)
                .where(BillingEvent.tenant_id == user_id)
            )
        ).scalar_one()
    )

    # Cost sorting ranks money leaving the wallet. Grants and adjustments are
    # positive, so they are parked at the end instead of topping "lowest cost"
    # or "highest cost" every time — those views exist to inspect AI spend.
    spend_case = case(
        (BillingEvent.amount_cents < 0, BillingEvent.amount_cents),
        else_=None,
    )
    if sort == "oldest":
        order_by = (BillingEvent.created_at.asc(), BillingEvent.id.asc())
    elif sort == "cost_high":
        order_by = (
            spend_case.asc().nulls_last(),
            BillingEvent.created_at.desc(),
            BillingEvent.id.desc(),
        )
    elif sort == "cost_low":
        order_by = (
            spend_case.desc().nulls_last(),
            BillingEvent.created_at.desc(),
            BillingEvent.id.desc(),
        )
    else:
        order_by = (BillingEvent.created_at.desc(), BillingEvent.id.desc())

    ledger_rows = (
        await db.execute(
            _select(BillingEvent)
            .where(BillingEvent.tenant_id == user_id)
            .order_by(*order_by)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()

    # A ledger row carries the model and money, but not why the call happened.
    # The purpose lives on the metered usage row (review analysis, reply,
    # assistant, etc.), linked by ledger_id. Surface it so the tenant can see
    # what consumed their credit instead of a wall of identical model rows.
    usage_purposes: dict[str, str | None] = {}
    usage_ids = [e.id for e in ledger_rows if e.kind == "ai_usage"]
    if usage_ids:
        purpose_rows = (
            await db.execute(
                _select(LLMUsageEvent.ledger_id, LLMUsageEvent.purpose).where(
                    LLMUsageEvent.ledger_id.in_(usage_ids)
                )
            )
        ).all()
        usage_purposes = {ledger_id: purpose for ledger_id, purpose in purpose_rows if ledger_id}

    def _row(e: BillingEvent) -> dict:
        row = {
            "id": e.id,
            "kind": e.kind,
            "status": e.status,
            "amount_cents": int(e.amount_cents or 0),
            "reserved_cents": int(e.reserved_cents or 0),
            "balance_after_cents": e.balance_after_cents,
            "purpose": usage_purposes.get(e.id),
            "prompt_tokens": int(e.prompt_tokens or 0),
            "completion_tokens": int(e.completion_tokens or 0),
            "idempotency_key": e.idempotency_key,
            "expires_at": e.expires_at.isoformat() if e.expires_at else None,
            "settled_at": e.settled_at.isoformat() if e.settled_at else None,
            "note": e.note,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        if include_model:
            row["model_id"] = e.model_id
        return row

    balance = int(user.ai_credit_cents or 0)
    status = "debt" if balance < 0 else "empty" if balance == 0 else "low" if balance < 100 else "ok"
    return {
        "tenant_id": user_id,
        "email": user.email,
        "plan": user.plan or "free",
        "balance_cents": balance,
        "held_cents": held_cents,
        "total_cents": balance + held_cents,
        "status": status,
        "total": total,
        "holds": [_row(h) for h in held_rows],
        "ledger": [_row(e) for e in ledger_rows],
    }
