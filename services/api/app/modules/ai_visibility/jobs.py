"""Durable grounded-research pipeline."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import sentry_sdk

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from ..jobs.models import Job
from ..locations.models import LocationProfile
from . import decisions, research, search, sources, validation
from .models import AiVisibilityRun, AiVisibilitySource
from .service import ACTIVE_RUN_STATUSES

logger = logging.getLogger(__name__)
MIN_SOURCES_FOR_BRIEF = 2
DEEP_MAX_SOURCES = 6
MIN_VALIDATED_CLAIMS = 1
LLM_PENDING_FAILURE_CODE = "llm_call_in_progress"
LLM_OUTCOME_UNKNOWN_FAILURE_CODE = "llm_outcome_unknown"
# Search and fetch are bounded to about a minute; allow enough lease for a
# slow provider response without letting an abandoned run block its prompt.
RESEARCH_LEASE_SECONDS = 15 * 60
USER_ERROR_MESSAGES = {
    "invalid_research_json": "The research model returned an unreadable brief. Please retry.",
    "no_llm_model_configured": "No research model is configured. Contact your workspace admin.",
    "search_unavailable": "Public web search is unavailable. Please retry shortly.",
    "search_blocked": "Public web search is temporarily paused. Please retry later.",
    "tenant_search_rate_limited": "This workspace reached its research limit. Wait a minute and retry.",
    "search_rate_limited": "Public web search is busy. Please retry shortly.",
    "uncited_answer_sentence": "The brief needs clearer citations. Please retry.",
    "unfetched_answer_url": "The brief included an unsupported link. Please retry.",
    "ungrounded_answer_sentence": "The brief could not be verified against its sources. Please retry.",
    "fabricated_answer_citation": "The brief included an unsupported citation. Please retry.",
}


def _client_error(exc: Exception) -> str:
    code = str(exc)
    return USER_ERROR_MESSAGES.get(
        code,
        USER_ERROR_MESSAGES.get(
            type(exc).__name__, "Research could not be completed. Please retry."
        ),
    )


class RunCancelled(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def load_branch_facts(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> dict:
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.user_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError("channel_not_owned")
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except (TypeError, ValueError):
        meta = {}
    listing_id = str(meta.get("location_id") or channel.listing_key or "")
    profile = (
        await db.execute(
            select(LocationProfile).where(
                LocationProfile.user_id == tenant_id,
                LocationProfile.listing_id == listing_id,
            )
        )
    ).scalar_one_or_none()
    return {
        "name": channel.display_name,
        "address": meta.get("address") or meta.get("locality"),
        "phone": meta.get("phone"),
        "website": meta.get("website"),
        "maps_url": meta.get("maps_url"),
        "categories": profile.categories if profile else {},
        "hours": profile.hours if profile else {},
        "description": profile.description if profile else None,
    }


def _source_payload(rows) -> list[dict]:
    return [
        {
            "id": row.id,
            "label": f"S{row.position + 1}",
            "title": row.title or row.url,
            "url": row.canonical_url or row.url,
            "excerpt": row.excerpt or "",
        }
        for row in rows
    ]


def _owned_search_results(branch: dict) -> list[search.SearchResult]:
    """Known public branch URLs are always worth reading.

    Search indexes can be sparse or geo-blind; the branch's own website and
    Maps listing are still direct public evidence and must not be lost just
    because no search provider indexed them.
    """
    rows: list[search.SearchResult] = []
    seen: set[str] = set()
    for key, title in (("website", "Branch website"), ("maps_url", "Google Maps")):
        url = str(branch.get(key) or "").strip()
        if not url or url == "about:blank":
            continue
        canonical = search.canonical_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)
        rows.append(search.SearchResult(url=canonical, title=title, snippet=""))
    return rows


def _merge_candidates(
    owned: list[search.SearchResult],
    relevant: list[search.SearchResult],
    *,
    max_results: int = 20,
) -> list[search.SearchResult]:
    """Put known owned URLs first, then only brand-relevant search hits."""
    out: list[search.SearchResult] = []
    seen: set[str] = set()
    for row in owned + relevant:
        key = search.canonical_url(row.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= max_results:
            break
    return out


def _is_owned_url(url: str, branch: dict) -> bool:
    """Classify owned evidence by its actual host, never by search snippets."""
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    if not host:
        return False
    owned_hosts = set()
    for key in ("website", "maps_url"):
        value = str(branch.get(key) or "")
        candidate = value if "//" in value else f"https://{value}"
        owned_hosts.add(
            (urlsplit(candidate).hostname or "").casefold().removeprefix("www.")
        )
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in owned_hosts
        if domain
    )


GENERIC_BRANCH_WORDS = {
    "company",
    "branch",
    "business",
    "location",
    "store",
    "shop",
    "restaurant",
    "services",
    "nearby",
    "best",
}


def _branch_tokens(branch: dict) -> set[str]:
    name = str(branch.get("name") or "")
    locality = " ".join(
        str(value or "")
        for value in (branch.get("address"), branch.get("locality"))
    )
    name_tokens = {
        token
        for token in re.findall(r"[a-z0-9\u0600-\u06ff]{4,}", name.casefold())
        if token not in GENERIC_BRANCH_WORDS
    }
    locality_tokens = set(
        re.findall(r"[a-z0-9\u0600-\u06ff]{4,}", locality.casefold())
    )
    # A city or district alone is not evidence about this branch. Require the
    # distinctive part of the name (e.g. "sayvors"), not "makkah".
    distinctive = name_tokens - locality_tokens
    return distinctive or name_tokens


def _mentions_branch(row, tokens: set[str]) -> bool:
    """True when a fetched page's own text names the branch.

    Unlike the gate on *usable* sources, this counts every readable page, so
    the facts rail can report how many of the pages actually read mention the
    branch instead of only the ones the brief cited.
    """
    if not tokens:
        return True
    text = " ".join(
        str(getattr(row, name, "") or "")
        for name in ("url", "title", "snippet", "excerpt")
    ).casefold()
    return any(token in text for token in tokens)


def _sources_are_relevant(rows, branch: dict) -> bool:
    tokens = _branch_tokens(branch)
    if not tokens:
        return True
    for row in rows:
        text = f"{row.title or ''} {row.snippet or ''} {row.excerpt or ''}".casefold()
        if any(token in text for token in tokens):
            return True
    return False


async def _status(db: AsyncSession, run: AiVisibilityRun, status: str) -> None:
    run.status = status
    run.updated_at = _now()
    if status == "searching" and run.started_at is None:
        run.started_at = _now()
    await db.commit()


async def _ensure_active(
    db: AsyncSession,
    run_id: str,
    tenant_id: str,
    *,
    job_id: str,
    lease_owner: str | None,
) -> None:
    """Reject deleted, terminal, cancelled, or reclaimed runs before external work."""
    row = (
        await db.execute(
            select(AiVisibilityRun.id, AiVisibilityRun.status, AiVisibilityRun.job_id).where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == tenant_id,
            )
        )
    ).one_or_none()
    if row is None or row.status not in ACTIVE_RUN_STATUSES or row.job_id != job_id:
        raise RunCancelled("run_cancelled")
    current_job = (
        await db.execute(
            select(Job.id).where(
                Job.id == job_id,
                Job.tenant_id == tenant_id,
                Job.subject_id == run_id,
                Job.status == "running",
                Job.lease_owner == lease_owner,
                Job.lease_expires_at > _now(),
            )
        )
    ).scalar_one_or_none()
    if current_job is None:
        raise RunCancelled("run_cancelled")


async def _set_terminal(
    db: AsyncSession,
    run_id: str,
    tenant_id: str,
    *,
    job,
    status: str,
    failure_code: str,
    error: str,
) -> AiVisibilityRun | None:
    """Persist a terminal state in a fresh transaction after any failed write."""
    await db.rollback()
    run = (
        await db.execute(
            select(AiVisibilityRun).where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        # The runner still owns this ORM object after the handler returns.
        # Rollback expired it, so reload before handing control back.
        await db.refresh(job)
        return None
    run.status = status
    run.failure_code = failure_code
    run.error = error
    run.updated_at = _now()
    run.completed_at = _now()
    await db.commit()
    await db.refresh(job)
    return run


async def _owned_evidence_fallback(
    db: AsyncSession,
    run: AiVisibilityRun,
    branch: dict,
    fetched_owned: list[AiVisibilitySource] | None = None,
):
    """Build a truthful brief when search finds no third-party coverage.

    Fetched owned pages are kept as the actual evidence (never replaced with
    a synthetic address sentence), so the owner sees what their own public
    website says instead of a tool that only echoes the location record.
    """
    name = str(branch.get("name") or run.prompt_snapshot)
    # Abbreviation dots ("Dist.") would split the templated answer into an
    # uncited sentence and trip our own citation validator; flatten them and
    # reuse the cleaned address everywhere (facts, claim, quote, answer).
    address = " ".join(str(branch.get("address") or "").replace(".", " ").split())
    website = str(branch.get("website") or "")
    maps_url = str(branch.get("maps_url") or "")
    safe_name = " ".join(name.replace(".", " ").split())
    listing = (
        f"{safe_name} is located at {address}."
        if address
        else f"{safe_name} is a verified branch."
    )
    finding = (
        f"We found no independent public pages that mention {safe_name}"
        + (f" in {address}" if address else "")
        + "."
    )
    impact = (
        "Because AI assistants rely on public web sources, they currently have no "
        "third-party evidence to cite or recommend this branch."
    )

    owned_rows = list(fetched_owned or [])
    if owned_rows:
        # Keep only the actual owned evidence in the final source list; the
        # irrelevant search snapshots that led us here are not citations.
        await db.execute(
            delete(AiVisibilitySource).where(
                AiVisibilitySource.run_id == run.id,
                AiVisibilitySource.id.not_in([row.id for row in owned_rows]),
            )
        )
        for index, row in enumerate(owned_rows):
            row.position = index
        await db.commit()
    else:
        facts = f"{listing} {finding} {impact}"
        await db.execute(
            delete(AiVisibilitySource).where(AiVisibilitySource.run_id == run.id)
        )
        owned_rows = [
            AiVisibilitySource(
                run_id=run.id,
                position=0,
                url=website or maps_url or "about:blank",
                canonical_url=website or maps_url or "about:blank",
                title=f"{name} (owned profile)",
                excerpt=facts,
            ),
            AiVisibilitySource(
                run_id=run.id,
                position=1,
                url=maps_url or website or "about:blank",
                canonical_url=maps_url or website or "about:blank",
                title=f"{name} on Google Maps",
                excerpt=facts,
            ),
        ]
        db.add_all(owned_rows)
        await db.commit()

    website_row = next(
        (
            row
            for row in owned_rows
            if row.url and row.url != "about:blank" and _is_owned_url(row.url, branch)
        ),
        None,
    )
    website_excerpt = (website_row.excerpt or "").strip() if website_row else ""
    summary_source = (website_row.snippet or website_excerpt).strip() if website_row else ""
    claims: list[research.ResearchClaim] = []
    if website_excerpt and listing.rstrip(".") in website_excerpt:
        claims.append(
            research.ResearchClaim(
                claim=listing.rstrip("."),
                quote=listing.rstrip("."),
                source_ids=[f"S{website_row.position + 1}"],
            )
        )
    if website_excerpt:
        # One clean, bounded sentence from the real fetched page; no model
        # paraphrase, so the claim/quote remains verifiable against the
        # immutable snapshot and sentence splitting cannot trip on dots.
        summary = re.split(r"[.!?。！？]\s|\n", summary_source, maxsplit=1)[0].strip()
        summary = re.sub(r"https?://\S+", "", summary).strip()
        summary = " ".join(summary.split())[:400].rstrip(". ")
        if summary:
            label = f"S{website_row.position + 1}"
            claims.append(
                research.ResearchClaim(
                    claim=summary,
                    quote=summary,
                    source_ids=[label],
                )
            )
            payload = research.ResearchPayload(
                answer=f"{summary} [{label}]", claims=claims
            )
            return owned_rows, payload
    if not claims:
        claims.append(
            research.ResearchClaim(
                claim=listing.rstrip("."),
                quote=listing.rstrip("."),
                source_ids=[f"S{row.position + 1}" for row in owned_rows],
            )
        )
    payload = research.ResearchPayload(
        answer=f"{listing.rstrip('.')} [S{owned_rows[0].position + 1}]",
        claims=claims,
    )
    return owned_rows, payload


def _finish(run: AiVisibilityRun, started: float, status: str) -> dict:
    logger.info(
        "ai_visibility_research_finished",
        extra={
            "run_id": run.id,
            "tenant_id": run.tenant_id,
            "status": status,
            "duration_seconds": round(time.monotonic() - started, 3),
            "source_count": run.source_count,
            "model": run.model,
            "failure_code": run.failure_code,
        },
    )
    if status in {"ambiguous", "insufficient_evidence"}:
        sentry_sdk.capture_message(
            f"AI visibility research {status}",
            level="warning",
            extras={
                "run_id": run.id,
                "tenant_id": run.tenant_id,
                "failure_code": run.failure_code,
            },
        )
    return {"status": status, "run_id": run.id}


async def handle_research(job, db: AsyncSession) -> dict:
    from ..billing.budget import BudgetExhausted

    run_id = str((job.payload or {}).get("run_id") or "")
    tenant_id = job.tenant_id
    job_id = job.id
    lease_owner = job.lease_owner
    run = (
        await db.execute(
            select(AiVisibilityRun).where(
                AiVisibilityRun.id == run_id,
                AiVisibilityRun.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise ValueError("run_not_found")
    started = time.monotonic()
    if run.status == "completed":
        return _finish(run, started, "completed")

    async def ensure_active() -> None:
        await _ensure_active(
            db,
            run_id,
            tenant_id,
            job_id=job_id,
            lease_owner=lease_owner,
        )

    llm_attempted = False
    try:
        await ensure_active()
        if run.failure_code == LLM_PENDING_FAILURE_CODE:
            # A previous worker committed the intent to call the provider but
            # did not durably record the outcome. Repeating it could bill twice.
            run = await _set_terminal(
                db,
                run_id,
                tenant_id,
                job=job,
                status="ambiguous",
                failure_code=LLM_OUTCOME_UNKNOWN_FAILURE_CODE,
                error=(
                    "The research provider may have completed, but its result "
                    "could not be verified."
                ),
            )
            if run is None:
                return {"status": "cancelled", "run_id": run_id}
            return _finish(run, started, "ambiguous")

        branch = await load_branch_facts(db, tenant_id, run.channel_id)
        coverage = dict(run.evidence_coverage or {})
        snapshots = list(
            (
                await db.execute(
                    select(AiVisibilitySource)
                    .where(AiVisibilitySource.run_id == run_id)
                    .order_by(AiVisibilitySource.position)
                )
            ).scalars().all()
        )
        if not snapshots:
            await _status(db, run, "searching")
            await ensure_active()
            queries = search.build_queries(
                run.prompt_snapshot, branch, run.research_depth or "quick"
            )
            providers: list[str] = []
            distinctive = _branch_tokens(branch)
            if run.research_depth == "deep":
                results = await search.search_many(
                    tenant_id,
                    queries,
                    distinctive=distinctive,
                    providers=providers,
                )
            else:
                results = await search.search_public_web(
                    tenant_id,
                    queries[0],
                    distinctive=distinctive,
                    providers=providers,
                )
            search_results = list(results)
            # Never waste the fetch budget on pages that do not mention the
            # branch. Search engines fill empty indexes with generic filler;
            # known owned URLs are kept separately and fetched first.
            relevant_results = [
                row
                for row in search_results
                if not distinctive
                or search._row_matches_tokens(row, distinctive)
            ]
            owned_candidates = _owned_search_results(branch)
            results = _merge_candidates(
                owned_candidates, relevant_results, max_results=20
            )
            await ensure_active()
            await _status(db, run, "fetching")
            snapshots, read_stats = await sources.fetch_sources(
                db,
                run_id,
                results,
                max_sources=DEEP_MAX_SOURCES
                if run.research_depth == "deep"
                else sources.MAX_SOURCES_PER_RUN,
            )
            await ensure_active()
            domains_seen = {
                (urlsplit(row.url).hostname or "").casefold().removeprefix("www.")
                for row in results
            } - {""}
            coverage["search"] = {
                "provider": " + ".join(dict.fromkeys(providers))
                or search.BING_PROVIDER_LABEL,
                "query": " | ".join(queries),
                "result_count": len(results),
                "search_candidate_count": len(search_results),
                "relevant_candidate_count": len(relevant_results),
                "owned_candidate_count": len(owned_candidates),
                "fetched_count": len(snapshots),
                "depth": run.research_depth or "quick",
            }
            coverage["metrics"] = {
                "queries_run": len(queries),
                "candidates_found": len(results),
                "domains_found": len(domains_seen),
                "pages_read": int(read_stats.get("pages_read", 0)),
                "pages_failed": int(read_stats.get("pages_failed", 0)),
                "links_found": int(read_stats.get("links_found", 0)),
                "words_read": int(read_stats.get("words_read", 0)),
                "brand_mentions": sum(
                    1 for row in snapshots if _mentions_branch(row, distinctive)
                ),
            }
        usable = [row for row in snapshots if row.excerpt]
        owned_usable = [row for row in usable if _is_owned_url(row.url, branch)]
        independent_usable = [
            row for row in usable if not _is_owned_url(row.url, branch)
        ]
        if not _sources_are_relevant(independent_usable, branch):
            query = str((coverage.get("search") or {}).get("query") or "").split(" | ")[0]
            try:
                coverage["platforms"] = await search.discover_public_profiles(
                    tenant_id, query or run.prompt_snapshot, str(branch.get("name") or "")
                )
            except Exception:
                logger.exception(
                    "ai_visibility_platform_discovery_failed",
                    extra={"run_id": run_id, "tenant_id": tenant_id},
                )
                coverage["platforms"] = []
            platforms = coverage["platforms"] or []
            metrics = dict(coverage.get("metrics") or {})
            metrics["platforms_checked"] = len(platforms)
            metrics["platforms_found"] = sum(
                1 for p in platforms if p.get("status") == "found"
            )
            coverage["metrics"] = metrics
            owned_rows, payload = await _owned_evidence_fallback(
                db, run, branch, owned_usable
            )
            source_payload = _source_payload(owned_rows)
            payload = validation.validate(payload, source_payload, branch)
            run.status = "insufficient_evidence"
            run.failure_code = "no_third_party_evidence"
            run.error = (
                "No independent public page discusses this branch. "
                "The brief uses the verified owned profile and shows what to fix."
            )
            run.answer_text = payload.answer
            run.mentioned = payload.mentioned
            run.cited = payload.cited
            run.recommended = payload.recommended
            run.incorrect = payload.incorrect
            run.validation_status = "passed"
            validated = sum(1 for row in payload.claims if row.status == "supported")
            run.evidence_coverage = {
                **coverage,
                "source_count": len(owned_rows),
                "validated_claim_count": validated,
                "unsupported_claim_count": 0,
                "third_party_source_count": 0,
                "owned_source_count": len(owned_rows),
            }
            run.source_count = len(owned_rows)
            run.validated_claim_count = validated
            run.unsupported_claim_count = 0
            run.competitor_mentions = []
            run.claims_json = [row.model_dump() for row in payload.claims]
            run.actions_json = [
                {
                    "priority": "P0",
                    "category": "content_gap",
                    "title": "Create or verify your Google Business Profile",
                    "rationale": (
                        "AI assistants and local search rely heavily on Google Maps "
                        "listings. A verified profile with the exact branch name, "
                        "address, phone, hours, and category is the fastest way to "
                        "create citable public evidence."
                    ),
                    "deep_link": "/dashboard/locations?tab=details",
                    "effort": "medium",
                    "evidence": {"source_ids": ["S1", "S2"]},
                },
                {
                    "priority": "P1",
                    "category": "content_gap",
                    "title": "Publish a public branch page on your website",
                    "rationale": (
                        "Add a page that names the branch, district, city, services, "
                        "and contact details. Independent pages that reference or "
                        "link to it become evidence AI can cite."
                    ),
                    "deep_link": "/dashboard/channels",
                    "effort": "medium",
                    "evidence": {"source_ids": ["S1"]},
                },
                {
                    "priority": "P1",
                    "category": "content_gap",
                    "title": "Get listed in trusted local directories",
                    "rationale": (
                        "Listings on reputable directories and industry registries "
                        "create third-party coverage. Use the same branch name, "
                        "address, and phone everywhere so sources agree."
                    ),
                    "deep_link": "/dashboard/channels",
                    "effort": "low",
                    "evidence": {"third_party_source_count": 0},
                },
            ]
            run.completed_at = _now()
            await db.commit()
            return _finish(run, started, run.status)
        if len(usable) < MIN_SOURCES_FOR_BRIEF:
            run = await _set_terminal(
                db,
                run_id,
                tenant_id,
                job=job,
                status="insufficient_evidence",
                failure_code="insufficient_sources",
                error="Not enough usable public sources were found for this question.",
            )
            if run is None:
                return {"status": "cancelled", "run_id": run_id}
            run.source_count = len(snapshots)
            run.evidence_coverage = {
                **coverage,
                "source_count": len(snapshots),
                "usable_source_count": len(usable),
                "validated_claim_count": 0,
                "unsupported_claim_count": 0,
                "third_party_source_count": 0,
                "owned_source_count": 0,
            }
            await db.commit()
            return _finish(run, started, run.status)

        await _status(db, run, "reading")
        await ensure_active()
        source_payload = _source_payload(usable)
        await _status(db, run, "writing")
        await ensure_active()
        extended = await db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.tenant_id == tenant_id,
                Job.status == "running",
                Job.lease_owner == lease_owner,
            )
            .values(lease_expires_at=_now() + timedelta(seconds=RESEARCH_LEASE_SECONDS))
        )
        if extended.rowcount != 1:
            raise RunCancelled("run_cancelled")
        run.failure_code = LLM_PENDING_FAILURE_CODE
        await db.commit()
        await ensure_active()
        llm_attempted = True
        model, payload = await research.complete_research(
            db,
            tenant_id=tenant_id,
            channel_id=run.channel_id,
            branch=branch,
            prompt=run.prompt_snapshot,
            locale=run.locale,
            sources=source_payload,
        )
        await ensure_active()
        await _status(db, run, "validating")
        payload = validation.validate(payload, source_payload, branch)
        validated_claims = sum(
            row.status == "supported" for row in payload.claims
        )
        unsupported_claims = sum(
            row.status == "unsupported" for row in payload.claims
        )
        if validated_claims < MIN_VALIDATED_CLAIMS:
            run.status = "insufficient_evidence"
            run.failure_code = "insufficient_validated_claims"
        else:
            run.status = "completed"
            run.failure_code = None

        run.model = model
        run.answer_text = payload.answer
        run.mentioned = payload.mentioned
        run.cited = payload.cited
        run.recommended = payload.recommended
        run.incorrect = payload.incorrect
        run.validation_status = "partial" if unsupported_claims else "passed"
        run.evidence_coverage = {
            **coverage,
            "source_count": len(usable),
            "validated_claim_count": validated_claims,
            "unsupported_claim_count": unsupported_claims,
            "third_party_source_count": len(usable),
            "owned_source_count": 0,
        }
        run.source_count = len(usable)
        run.validated_claim_count = validated_claims
        run.unsupported_claim_count = unsupported_claims
        run.competitor_mentions = [
            row.model_dump() for row in payload.competitors
        ]
        run.claims_json = [row.model_dump() for row in payload.claims]
        run.actions_json = decisions.build_actions(payload, branch=branch)
        run.completed_at = _now()
        await db.commit()
        return {"status": run.status, "run_id": run_id}
    except RunCancelled:
        return {"status": "cancelled", "run_id": run_id}
    except BudgetExhausted:
        logger.warning(
            "ai_visibility_budget_exhausted",
            extra={"run_id": run_id, "tenant_id": tenant_id},
        )
        run = await _set_terminal(
            db,
            run_id,
            tenant_id,
            job=job,
            status="failed",
            failure_code="budget_exhausted",
            error="AI credits are exhausted.",
        )
    except search.SearchRateLimited as exc:
        if not isinstance(exc, search.TenantSearchRateLimited) and (
            int(job.attempts or 0) + 1 < int(job.max_attempts or 1)
        ):
            # Shared provider quota is temporary. Let the durable runner defer
            # this attempt instead of failing one tenant because another is busy.
            logger.info(
                "ai_visibility_search_deferred",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
            raise
        logger.warning(
            "ai_visibility_research_rejected code=%s detail=%s",
            type(exc).__name__,
            str(exc)[:200],
            extra={
                "run_id": run_id,
                "tenant_id": tenant_id,
                "failure_code": type(exc).__name__,
            },
        )
        run = await _set_terminal(
            db,
            run_id,
            tenant_id,
            job=job,
            status="failed",
            failure_code=type(exc).__name__,
            error=_client_error(exc),
        )
    except (
        search.SearchUnavailable,
        research.ResearchValidationError,
        validation.CitationValidationError,
    ) as exc:
        logger.warning(
            "ai_visibility_research_rejected code=%s detail=%s",
            type(exc).__name__,
            str(exc)[:200],
            extra={
                "run_id": run_id,
                "tenant_id": tenant_id,
                "failure_code": type(exc).__name__,
            },
        )
        run = await _set_terminal(
            db,
            run_id,
            tenant_id,
            job=job,
            status="failed",
            failure_code=type(exc).__name__,
            error=_client_error(exc),
        )
    except Exception as exc:
        if llm_attempted:
            # Once the provider call may have succeeded, a local failure is not
            # proof that no spend occurred. Surface it instead of auto-repeating.
            logger.exception(
                "ai_visibility_post_llm_failure",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
            status = "ambiguous"
            failure_code = "post_llm_persistence_failed"
            error = (
                "The research provider completed, but its result could not be "
                "saved safely. Please verify before retrying."
            )
        else:
            logger.exception(
                "ai_visibility_research_failed",
                extra={"run_id": run_id, "tenant_id": tenant_id},
            )
            status = "failed"
            failure_code = "research_failed"
            error = "Research could not be completed. Please retry."
        run = await _set_terminal(
            db,
            run_id,
            tenant_id,
            job=job,
            status=status,
            failure_code=failure_code,
            error=error,
        )
    if run is None:
        return {"status": "cancelled", "run_id": run_id}
    return _finish(run, started, run.status)
