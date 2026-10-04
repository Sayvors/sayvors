"""LLM metering: per-call usage events + aggregations.

Recording is fire-and-forget from LLMProvider.complete() — it gets its own
DB session, swallows all errors, and never blocks or breaks generation.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, or_, select

logger = logging.getLogger(__name__)

# Voice TTS metering lives in the same events table (dotted purpose), but
# characters-spoken are not LLM tokens — the token overviews below exclude
# anything under this prefix; the admin voice endpoint serves that slice.
VOICE_PURPOSE_PREFIX = "voice."


def _non_voice():
    """Filter keeping legacy NULL-purpose rows while dropping voice events."""
    from .models import LLMUsageEvent

    return or_(LLMUsageEvent.purpose.is_(None),
               ~LLMUsageEvent.purpose.like(VOICE_PURPOSE_PREFIX + "%"))

# Overridable in tests (defaults to the production session factory).
_session_factory = None

# Live background inserts (also lets tests await them).
_pending: set = set()


def _get_session_factory():
    if _session_factory is not None:
        return _session_factory
    from ...database import async_session

    return async_session


def record_usage_event(req, resp, latency_ms: int, status: str = "ok", error: str | None = None):
    """Schedule a usage-event insert. Never raises; returns the task (or None)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None  # no loop (tests/shell) — skip silently
    task = loop.create_task(_insert_event(req, resp, latency_ms, status, error))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return task


async def _insert_event(req, resp, latency_ms: int, status: str, error: str | None) -> None:
    try:
        from .models import LLMUsageEvent

        usage = resp.usage if resp is not None else None
        async with _get_session_factory()() as db:
            db.add(LLMUsageEvent(
                tenant_id=getattr(req, "tenant_id", None),
                provider=(resp.provider if resp is not None else None)
                or _provider_from_model(getattr(req, "model_id", None)),
                model_id=getattr(req, "model_id", None),
                api_model=getattr(req, "model", "") or "",
                purpose=getattr(req, "purpose", None),
                channel_id=getattr(req, "channel_id", None),
                prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(usage, "total_tokens", 0) or 0,
                latency_ms=latency_ms,
                status=status,
                error=error,
            ))
            await db.commit()
    except Exception as e:
        logger.warning("Usage event insert failed (metering only): %s", e)


def _provider_from_model(model_id: str | None) -> str:
    if model_id and ":" in model_id:
        return model_id.split(":", 1)[0]
    return "unknown"


async def get_tenant_summary(db, tenant_id: str, days: int = 30) -> dict:
    """Totals + per-model + per-purpose + daily series for one tenant."""
    from sqlalchemy import func

    from .models import LLMUsageEvent

    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = [LLMUsageEvent.tenant_id == tenant_id, LLMUsageEvent.created_at >= since,
            _non_voice()]

    totals = (await db.execute(
        select(func.count().label("calls"),
               func.coalesce(func.sum(LLMUsageEvent.prompt_tokens), 0).label("prompt"),
               func.coalesce(func.sum(LLMUsageEvent.completion_tokens), 0).label("completion"),
               func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total"),
               func.coalesce(func.avg(LLMUsageEvent.latency_ms), 0).label("avg_ms"))
        .select_from(LLMUsageEvent).where(*base)
    )).one()

    by_model = (await db.execute(
        select(LLMUsageEvent.model_id, LLMUsageEvent.api_model,
               func.count().label("calls"),
               func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total"),
               func.coalesce(func.avg(LLMUsageEvent.latency_ms), 0).label("avg_ms"))
        .select_from(LLMUsageEvent).where(*base)
        .group_by(LLMUsageEvent.model_id, LLMUsageEvent.api_model)
        .order_by(func.sum(LLMUsageEvent.total_tokens).desc())
    )).all()

    by_purpose = (await db.execute(
        select(LLMUsageEvent.purpose,
               func.count().label("calls"),
               func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total"))
        .select_from(LLMUsageEvent).where(*base)
        .group_by(LLMUsageEvent.purpose)
        .order_by(func.sum(LLMUsageEvent.total_tokens).desc())
    )).all()

    daily = (await db.execute(
        select(func.date(LLMUsageEvent.created_at).label("day"),
               func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total"),
               func.coalesce(func.sum(LLMUsageEvent.prompt_tokens), 0).label("prompt"),
               func.coalesce(func.sum(LLMUsageEvent.completion_tokens), 0).label("completion"),
               func.coalesce(func.avg(LLMUsageEvent.latency_ms), 0).label("avg_ms"),
               func.count().label("calls"))
        .select_from(LLMUsageEvent).where(*base)
        .group_by(func.date(LLMUsageEvent.created_at))
        .order_by("day")
    )).all()

    return {
        "days": days,
        "totals": {"calls": totals.calls,
                   "prompt_tokens": int(totals.prompt),
                   "completion_tokens": int(totals.completion),
                   "total_tokens": int(totals.total),
                   "avg_latency_ms": int(totals.avg_ms)},
        "by_model": [{"model": m.model_id or m.api_model, "api_model": m.api_model,
                      "calls": m.calls, "total_tokens": int(m.total),
                      "avg_latency_ms": int(m.avg_ms)} for m in by_model],
        "by_purpose": [{"purpose": p.purpose or "unknown", "calls": p.calls,
                        "total_tokens": int(p.total)} for p in by_purpose],
        "daily": [{"day": str(d.day), "total_tokens": int(d.total),
                   "prompt_tokens": int(d.prompt), "completion_tokens": int(d.completion),
                   "avg_latency_ms": int(d.avg_ms), "calls": d.calls}
                  for d in daily],
    }


async def get_admin_overview(db, days: int = 30, limit: int = 50) -> dict:
    """Global totals + per-tenant + per-model tables for the admin dashboard."""
    from sqlalchemy import func

    from ..users.models import User
    from .models import LLMUsageEvent

    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = [LLMUsageEvent.created_at >= since, _non_voice()]

    totals = (await db.execute(
        select(func.count().label("calls"),
               func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total"),
               func.count(func.distinct(LLMUsageEvent.tenant_id)).label("tenants"))
        .select_from(LLMUsageEvent).where(*base)
    )).one()

    per_tenant = (await db.execute(
        select(LLMUsageEvent.tenant_id,
               func.count().label("calls"),
               func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total"),
               func.coalesce(func.avg(LLMUsageEvent.latency_ms), 0).label("avg_ms"),
               func.max(LLMUsageEvent.created_at).label("last_seen"))
        .select_from(LLMUsageEvent).where(*base)
        .group_by(LLMUsageEvent.tenant_id)
        .order_by(func.sum(LLMUsageEvent.total_tokens).desc())
        .limit(limit)
    )).all()

    emails: dict[str, str] = {}
    tenant_ids = [t.tenant_id for t in per_tenant if t.tenant_id]
    if tenant_ids:
        rows = (await db.execute(
            select(User.id, User.email).where(User.id.in_(tenant_ids))
        )).all()
        emails = {str(uid): email for uid, email in rows}

    per_model = (await db.execute(
        select(LLMUsageEvent.model_id, LLMUsageEvent.api_model,
               func.count().label("calls"),
               func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total"))
        .select_from(LLMUsageEvent).where(*base)
        .group_by(LLMUsageEvent.model_id, LLMUsageEvent.api_model)
        .order_by(func.sum(LLMUsageEvent.total_tokens).desc())
        .limit(50)
    )).all()

    daily = (await db.execute(
        select(func.date(LLMUsageEvent.created_at).label("day"),
               func.coalesce(func.sum(LLMUsageEvent.total_tokens), 0).label("total"),
               func.count().label("calls"))
        .select_from(LLMUsageEvent).where(*base)
        .group_by(func.date(LLMUsageEvent.created_at))
        .order_by("day")
    )).all()

    return {
        "days": days,
        "totals": {"calls": totals.calls, "total_tokens": int(totals.total),
                   "active_tenants": totals.tenants},
        "per_tenant": [{"tenant_id": t.tenant_id,
                        "email": emails.get(t.tenant_id or "", "—"),
                        "calls": t.calls, "total_tokens": int(t.total),
                        "avg_latency_ms": int(t.avg_ms),
                        "last_seen": t.last_seen.isoformat() if t.last_seen else None}
                       for t in per_tenant],
        "per_model": [{"model": m.model_id or m.api_model, "api_model": m.api_model,
                       "calls": m.calls, "total_tokens": int(m.total)} for m in per_model],
        "daily": [{"day": str(d.day), "total_tokens": int(d.total), "calls": d.calls}
                  for d in daily],
    }


def record_voice_event(tenant_id: str | None, provider: str, model_id: str,
                       api_model: str, chars: int, latency_ms: int,
                       status: str = "ok", error: str | None = None):
    """Meter one TTS synthesis — fire-and-forget, never raises.

    Same events table as LLM calls (purpose "voice.tts"); characters spoken
    land in completion/total so per-engine char bars are possible, while the
    token overviews above exclude the voice.* prefix.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None  # no loop (tests/shell) — skip silently
    task = loop.create_task(_insert_voice_event(
        tenant_id, provider, model_id, api_model, chars, latency_ms, status, error))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    return task


async def _insert_voice_event(tenant_id: str | None, provider: str, model_id: str,
                              api_model: str, chars: int, latency_ms: int,
                              status: str, error: str | None) -> None:
    try:
        from .models import LLMUsageEvent

        async with _get_session_factory()() as db:
            db.add(LLMUsageEvent(
                tenant_id=tenant_id,
                provider=provider or "unknown",
                model_id=model_id,
                api_model=api_model or "",
                purpose="voice.tts",
                prompt_tokens=0,
                completion_tokens=max(0, int(chars or 0)),
                total_tokens=max(0, int(chars or 0)),
                latency_ms=max(0, int(latency_ms or 0)),
                status=status,
                error=(error or "")[:300] or None,
            ))
            await db.commit()
    except Exception as e:
        logger.warning("Voice usage insert failed (metering only): %s", e)


async def get_voice_overview(db, days: int = 30) -> dict:
    """Voice-model (TTS) metering for the admin dashboard: totals +
    per-engine bars + daily series. Only purpose "voice.tts" rows."""
    from .models import LLMUsageEvent

    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = [LLMUsageEvent.created_at >= since,
            LLMUsageEvent.purpose == "voice.tts"]
    ok = LLMUsageEvent.status == "ok"

    totals = (await db.execute(
        select(func.count().label("calls"),
               func.coalesce(func.sum(case((ok, 1), else_=0)), 0).label("notes"),
               func.coalesce(func.sum(case((ok, LLMUsageEvent.total_tokens), else_=0)), 0).label("chars"),
               func.coalesce(func.sum(case((~ok, 1), else_=0)), 0).label("failed"),
               func.coalesce(func.avg(LLMUsageEvent.latency_ms), 0).label("avg_ms"),
               func.count(func.distinct(LLMUsageEvent.model_id)).label("engines"))
        .select_from(LLMUsageEvent).where(*base)
    )).one()

    per_engine = (await db.execute(
        select(LLMUsageEvent.model_id, LLMUsageEvent.api_model, LLMUsageEvent.provider,
               func.count().label("calls"),
               func.coalesce(func.sum(case((ok, 1), else_=0)), 0).label("notes"),
               func.coalesce(func.sum(case((ok, LLMUsageEvent.total_tokens), else_=0)), 0).label("chars"),
               func.coalesce(func.sum(case((~ok, 1), else_=0)), 0).label("failures"),
               func.coalesce(func.avg(LLMUsageEvent.latency_ms), 0).label("avg_ms"))
        .select_from(LLMUsageEvent).where(*base)
        .group_by(LLMUsageEvent.model_id, LLMUsageEvent.api_model, LLMUsageEvent.provider)
        .order_by(func.sum(case((ok, 1), else_=0)).desc())
    )).all()

    daily = (await db.execute(
        select(func.date(LLMUsageEvent.created_at).label("day"),
               func.coalesce(func.sum(case((ok, 1), else_=0)), 0).label("notes"),
               func.coalesce(func.sum(case((ok, LLMUsageEvent.total_tokens), else_=0)), 0).label("chars"))
        .select_from(LLMUsageEvent).where(*base)
        .group_by(func.date(LLMUsageEvent.created_at))
        .order_by("day")
    )).all()

    return {
        "days": days,
        "totals": {"notes": int(totals.notes), "calls": totals.calls,
                   "failed": int(totals.failed), "chars": int(totals.chars),
                   "avg_latency_ms": int(totals.avg_ms),
                   "active_engines": int(totals.engines)},
        "per_engine": [{"engine": e.model_id or "voice:unknown",
                        "provider": e.provider or "",
                        "api_model": e.api_model or "",
                        "notes": int(e.notes), "calls": e.calls,
                        "chars": int(e.chars), "failures": int(e.failures),
                        "avg_latency_ms": int(e.avg_ms)} for e in per_engine],
        "daily": [{"day": str(d.day), "notes": int(d.notes), "chars": int(d.chars)}
                  for d in daily],
    }
