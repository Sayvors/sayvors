"""Retrieval mechanisms behind the Retrieval Layer.

Every mechanism is source-agnostic from the caller's view: each returns
plain (fact, score) pairs scoped to the tenant's databanks. No mechanism is
a "fallback" for another — the layer queries the applicable ones and merges.

Mechanisms:
- structured: exact rows from uploaded CSV/structured documents.
- hybrid: vector + keyword full-text over embedded chunks (RRF merge).
- external: controlled live-database lookup (schema discovery, then a
  read-only parameterized LIKE search — never interpolated SQL).
- identity: owner-configured facts (profile + offered services).
- domain: business-domain vocabulary for relevance assessment.

All probes run inside SAVEPOINTs and never raise: a failed probe yields no
facts and leaves the caller's session untouched.
"""
import csv
import logging
from io import StringIO

logger = logging.getLogger(__name__)

_MAX_EXTERNAL_SOURCES = 3
_MAX_EXTERNAL_TABLES = 5
_MAX_EXTERNAL_ROWS = 5


def _terms(query: str, min_len: int = 2) -> list[str]:
    terms = [t.lower() for t in (query or "").split() if len(t) >= min_len]
    return terms or ([query.lower()] if (query or "").strip() else [])


async def resolve_bank_ids(db, tenant_id: str, channel_id: str | None = None,
                           bank_id: str | None = None) -> list[str]:
    """Tenant-scoped databank ids: explicit > channel-linked > all tenant's."""
    from sqlalchemy import select

    from ..rag.models import Databank

    try:
        if bank_id:
            row = (
                await db.execute(
                    select(Databank.id).where(
                        Databank.id == bank_id, Databank.user_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            return [row] if row else []
        if channel_id:
            linked = await channel_bank_id(channel_id, tenant_id, db)
            if linked:
                return [linked]
        res = await db.execute(
            select(Databank.id).where(Databank.user_id == tenant_id)
        )
        return [r[0] for r in res.all()]
    except Exception as e:
        logger.debug("Bank resolution failed: %s", e)
        return []


async def channel_bank_id(channel_id: str | None, tenant_id: str, db) -> str | None:
    """The databank linked to this channel in Automations (if any)."""
    if not channel_id:
        return None
    try:
        from sqlalchemy import select

        from ..channels.models import AutoReplyConfig, Channel

        async with db.begin_nested():
            ch = (
                await db.execute(
                    select(Channel.id).where(
                        Channel.id == channel_id, Channel.user_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if not ch:
                return None
            return (
                await db.execute(
                    select(AutoReplyConfig.databank_id).where(
                        AutoReplyConfig.channel_id == channel_id
                    )
                )
            ).scalar_one_or_none()
    except Exception as e:
        logger.debug("Channel bank lookup failed: %s", e)
        return None


async def structured_lookup(db, tenant_id: str, bank_ids: list[str],
                            record_types: list[str], query: str,
                            limit: int = 5) -> list[tuple[str, float]]:
    """Exact rows from uploaded structured (CSV) documents.

    Scores by query-term coverage so the layer can merge-rank against
    hybrid results instead of short-circuiting on first hit.
    """
    from sqlalchemy import select

    from ..rag.models import Databank, Document

    if not bank_ids:
        return []
    try:
        async with db.begin_nested():
            docs = (
                await db.execute(
                    select(Document).where(
                        Document.databank_id.in_(bank_ids),
                        Document.user_id == tenant_id,
                        Document.file_type == "csv",
                    )
                )
            ).scalars().all()
    except Exception as e:
        logger.debug("Structured lookup doc scan failed: %s", e)
        return []

    q_terms = _terms(query)
    hits: list[tuple[str, float]] = []
    from ...core.storage import get_doc

    for doc in docs:
        try:
            content = get_doc(doc.databank_id, f"{doc.id}.{doc.file_type}")
        except FileNotFoundError:
            continue
        try:
            text = content.decode("utf-8", errors="replace").replace("\ufeff", "")
            reader = csv.DictReader(StringIO(text))
            wanted = [r.lower() for r in (record_types or [])]
            for row in reader:
                rt = (row.get("record_type") or "").strip().lower()
                if wanted and rt not in wanted:
                    continue
                searchable = " ".join([
                    row.get("name") or "",
                    row.get("category") or "",
                    row.get("description") or "",
                    row.get("entity_id") or "",
                ]).lower()
                matched = [t for t in q_terms if t in searchable]
                if not matched:
                    continue
                # Coverage score: exact structured matches outrank fuzzy ones
                # in the merge — by score, not by short-circuit.
                score = 0.6 + 0.4 * (len(matched) / max(len(q_terms), 1))
                # Keep link-bearing fields: the validator grounds URLs
                # against rendered facts, so source_url must survive.
                parts = [
                    f"{k}={v}" for k, v in row.items()
                    if k in ("name", "category", "description", "source_url",
                             "entity_id", "status") and v
                ]
                hits.append((", ".join(parts) if parts else str(row), score))
                if len(hits) >= limit * 3:
                    break
        except Exception as e:
            logger.debug("Structured lookup failed for doc %s: %s", doc.id, e)
            continue
    hits.sort(key=lambda h: h[1], reverse=True)
    return hits[:limit]


async def hybrid_lookup(db, bank_ids: list[str], query: str,
                        top_k: int = 5) -> list[tuple[str, float]]:
    """Vector + keyword (RRF) search over embedded chunks, all banks merged."""
    if not bank_ids or not (query or "").strip():
        return []
    try:
        from ..rag.embeddings import get_embedding_provider
        from ..rag.search import hybrid_search

        try:
            provider = await get_embedding_provider()
            vectors = await provider.embed([query[:500]])
            query_vector = vectors[0]
        except Exception:
            query_vector = None
        seen: dict[str, tuple[str, float]] = {}
        for bank_id in bank_ids:
            try:
                async with db.begin_nested():
                    results = await hybrid_search(
                        databank_id=bank_id,
                        query_vector=query_vector,
                        query_text=query[:500],
                        top_k=top_k,
                        db=db,
                    )
            except Exception as e:
                logger.debug("Hybrid lookup failed for bank %s: %s", bank_id, e)
                continue
            for r in results:
                content = (r.get("content") or "").strip()
                if not content:
                    continue
                key = content[:200]
                prev = seen.get(key)
                score = float(r.get("score") or 0)
                if prev is None or score > prev[1]:
                    seen[key] = (content[:800], score)
        ranked = sorted(seen.values(), key=lambda h: h[1], reverse=True)
        return ranked[:top_k]
    except Exception as e:
        logger.debug("Hybrid lookup failed: %s", e)
        return []


def _quote_ident(name: str) -> str:
    """Quote an SQL identifier (table/column). Values always use bind params."""
    return '"' + (name or "").replace('"', '""') + '"'


async def external_lookup(db, tenant_id: str, bank_ids: list[str], query: str,
                          limit: int = 5) -> list[tuple[str, float]]:
    """Controlled live-database lookup for the tenant's connected sources.

    Schema discovery first (information_schema text columns), then ONE
    read-only parameterized LIKE search per table — identifiers quoted,
    values bound, guarded by the connectors' read-only validator. Sources
    are tenant-scoped by bank; credentials never leave the server.
    """
    from sqlalchemy import select

    from ..rag.models import DataSource

    if not bank_ids or not (query or "").strip():
        return []
    try:
        async with db.begin_nested():
            sources = (
                await db.execute(
                    select(DataSource).where(
                        DataSource.databank_id.in_(bank_ids),
                        DataSource.user_id == tenant_id,
                    ).limit(_MAX_EXTERNAL_SOURCES)
                )
            ).scalars().all()
            source_rows = [
                (s.id, s.db_type, s.host, s.port, s.database,
                 s.username, s.password_encrypted)
                for s in sources
            ]
    except Exception as e:
        logger.debug("External lookup source scan failed: %s", e)
        return []

    terms = [t for t in _terms(query, min_len=3)][:4]
    if not terms:
        return []
    hits: list[tuple[str, float]] = []
    from ..rag.connectors import _fetch, validate_readonly_sql
    from ..rag.service import _config_from_source

    for (sid, db_type, _host, _port, _database, _username, _pwenc) in source_rows:
        try:
            from ..channels.service import decrypt_token
            from ..rag.connectors import DbConfig

            cfg = DbConfig(
                db_type=db_type,
                host=_host, port=_port, database=_database,
                username=_username,
                password=decrypt_token(_pwenc or ""),
            )
        except Exception as e:
            logger.debug("External lookup config failed for %s: %s", sid, e)
            continue
        ph = "$%d" if db_type == "postgres" else "%s"
        try:
            if db_type == "postgres":
                col_sql = (
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND data_type IN ('text','character varying','character') "
                    "ORDER BY table_name LIMIT 50"
                )
                col_rows, _ = await _fetch(cfg, col_sql)
            else:
                col_sql = (
                    "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() "
                    "AND DATA_TYPE IN ('text','varchar','char') "
                    "ORDER BY TABLE_NAME LIMIT 50"
                )
                col_rows, _ = await _fetch(cfg, col_sql)
        except Exception as e:
            logger.debug("External lookup schema discovery failed for %s: %s", sid, e)
            continue
        by_table: dict[str, list[str]] = {}
        for tname, cname in col_rows:
            by_table.setdefault(str(tname), []).append(str(cname))
        for tname in list(by_table)[:_MAX_EXTERNAL_TABLES]:
            cols = by_table[tname][:6]
            if not cols:
                continue
            conds = []
            args: list = []
            for i, term in enumerate(terms):
                for j, col in enumerate(cols):
                    if db_type == "postgres":
                        conds.append(f"{_quote_ident(col)} ILIKE ${len(args) + 1}")
                    else:
                        conds.append(f"{_quote_ident(col)} LIKE %s")
                    args.append(f"%{term}%")
            sql = (
                f"SELECT {', '.join(_quote_ident(c) for c in cols)} "
                f"FROM {_quote_ident(tname)} "
                f"WHERE {' OR '.join(conds)} LIMIT {limit}"
            )
            try:
                safe = validate_readonly_sql(sql, limit)
                columns, rows = await _fetch(cfg, safe, tuple(args))
            except Exception as e:
                logger.debug("External lookup query failed on %s: %s", tname, e)
                continue
            for row in rows[:limit]:
                pairs = [f"{c}={v}" for c, v in zip(columns, row) if v not in (None, "")]
                if pairs:
                    hits.append((", ".join(pairs)[:600], 0.5))
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    return hits[:limit]


async def identity_block(db, tenant_id: str | None,
                         channel_id: str | None = None) -> str:
    """Owner-configured identity facts (profile + offered services)."""
    try:
        from ..profile.service import (
            format_business_identity,
            get_business_context,
            get_offered_services,
        )

        return format_business_identity(
            await get_business_context(tenant_id, db),
            services=await get_offered_services(
                tenant_id, db, channel_id=channel_id
            ),
        )
    except Exception as e:
        logger.debug("Identity block unavailable: %s", e)
        return ""


def _words(text: str) -> list[str]:
    import re

    return [w for w in re.findall(r"[a-z0-9]{2,}", (text or "").lower())]


async def domain_vocabulary(db, tenant_id: str,
                            channel_id: str | None = None) -> dict:
    """Business-domain vocabulary for relevance assessment.

    Assembled from everything the tenant configured: business context,
    location profiles, channel services, channel display name, databank
    names + document filenames. The explicit "does NOT sell" list is
    returned separately under `not_offered` and is deliberately NOT part
    of `terms`.
    """
    from sqlalchemy import select

    terms: set[str] = set()
    not_offered: set[str] = set()
    sources: dict[str, int] = {}
    try:
        from ..channels.models import BusinessService, Channel
        from ..locations.models import LocationProfile
        from ..profile.service import get_business_context
        from ..rag.models import Databank, Document

        async def _safe(stmt, label: str):
            try:
                async with db.begin_nested():
                    return await db.execute(stmt)
            except Exception as e:
                if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
                    logger.debug("Domain %s skipped (table missing): %s", label, e)
                else:
                    logger.warning("Domain %s failed: %s", label, e)
                return None

        try:
            ctx = await get_business_context(tenant_id, db)
        except Exception as e:
            logger.debug("Business context unavailable: %s", e)
            ctx = {}
        if ctx:
            terms.update(_words(ctx.get("business_type") or ""))
            terms.update(_words(ctx.get("business_sells") or ""))
            terms.update(_words(ctx.get("business_description") or ""))
            not_offered.update(_words(ctx.get("business_doesnt_sell") or ""))
            sources["business_context"] = sum(1 for v in ctx.values() if v)

        res = await _safe(
            select(LocationProfile).where(LocationProfile.user_id == tenant_id),
            "location_profiles",
        )
        profiles = res.scalars().all() if res is not None else []
        for p in profiles:
            cats = p.categories or {}
            if isinstance(cats, dict):
                if cats.get("primary"):
                    terms.update(_words(str(cats["primary"])))
                for extra in cats.get("additional") or []:
                    terms.update(_words(str(extra)))
            terms.update(_words(p.description or ""))
        if profiles:
            sources["location_profiles"] = len(profiles)

        if channel_id:
            res = await _safe(
                select(BusinessService).where(
                    BusinessService.channel_id == channel_id
                ),
                "channel_services",
            )
            services = res.scalars().all() if res is not None else []
            for s in services:
                terms.update(_words(s.name or ""))
                terms.update(_words(s.category or ""))
                terms.update(_words(s.description or ""))
            if services:
                sources["channel_services"] = len(services)

            res = await _safe(
                select(Channel.display_name).where(
                    Channel.id == channel_id, Channel.user_id == tenant_id
                ),
                "channel",
            )
            ch = res.scalar_one_or_none() if res is not None else None
            if ch:
                terms.update(_words(ch))
                sources["channel_name"] = 1

        res = await _safe(
            select(Databank).where(Databank.user_id == tenant_id).limit(10),
            "databanks",
        )
        banks = res.scalars().all() if res is not None else []
        for b in banks:
            terms.update(_words(b.name or ""))
        if banks:
            import re as _re

            sources["databanks"] = len(banks)
            res = await _safe(
                select(Document.filename).where(
                    Document.databank_id.in_([b.id for b in banks])
                ).limit(50),
                "documents",
            )
            rows = res.all() if res is not None else []
            for (filename,) in rows:
                cleaned = _re.sub(r"\.[a-z0-9]+$", "", filename or "")
                terms.update(
                    w for w in _words(cleaned)
                    if w not in {"databank", "data", "csv", "final", "new"}
                )
            sources["documents"] = len(rows)
    except Exception as e:
        # Read-only probes: nothing to roll back, just log.
        if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
            logger.debug("Domain vocabulary failed (table missing): %s", e)
        else:
            logger.warning("Domain vocabulary failed: %s", e)
    return {"terms": sorted(terms), "sources": sources,
            "not_offered": sorted(not_offered)}
