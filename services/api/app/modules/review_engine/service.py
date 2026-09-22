"""Review engine orchestrator — strategy selection, evidence retrieval, generation."""
import json
import logging
import time
import uuid
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session as _async_session
from ..llm.providers.base import LLMMessage, LLMRequest, ProviderError
from ..llm.providers.registry import get_provider_for_model
from ..llm.service import _resolve_model
from ..retrieval.layer import identity as _layer_identity
from ..retrieval.layer import retrieve_evidence
from .generator import generate_response
from .issues import extract_issues
from .models import ReviewResponseLog
from .relevance import (
    apply_retrieval_corroboration,
    assess_relevance,
    resolve_business_domain,
)
from .schemas import (
    ExtractedIssue,
    GeneratedResponse,
    RelevanceVerdict,
    ReviewAnalysis,
    ReviewEngineRequest,
    ReviewEngineResponse,
    StrategyMatch,
    SuppressedStrategy,
    ToolCall,
    ValidationResult,
)
from .strategies import (
    BEST_EFFORT,
    CHANNEL_POLICIES,
    DEFAULT_BRAND_VOICE,
    evidence_needs_for,
    prune_unsatisfiable,
    resolve_strategy_conflicts,
    search_strategies,
    select_execution_set,
)
from .understanding import analyze_review
from .validator import select_tier, validate_response

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3


async def _resolve_engine_model(req: ReviewEngineRequest, tenant_id: str, db: AsyncSession) -> tuple[str, str]:
    """Resolve which model the engine must use. Returns (model_id, source).

    Priority:
      1. Explicit `model` in the request (playground / API override) —
         validated against the enabled list.
      2. The channel's explicit model choice — validated the same way.
      3. The tenant's first enabled model ("tenant-default").

    No silent defaults, no hardcoded provider, no fallback models. The
    admin-managed database is the only source of truth; anything
    unresolvable raises ValueError telling the user what to fix.
    """
    from sqlalchemy import select

    from ..llm.service import resolve_tenant_model

    if req.model:
        return await resolve_tenant_model(db, preferred=req.model), "request"

    if req.channel_id:
        from ..channels.models import AutoReplyConfig, Channel

        ch = (
            await db.execute(
                select(Channel.id).where(
                    Channel.id == req.channel_id, Channel.user_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if not ch:
            raise ValueError("Channel not found")
        cfg = (
            await db.execute(
                select(AutoReplyConfig.model).where(
                    AutoReplyConfig.channel_id == req.channel_id
                )
            )
        ).scalar_one_or_none()
        if cfg:
            return await resolve_tenant_model(db, preferred=cfg), "channel"

    return await resolve_tenant_model(db), "tenant-default"


async def _resolve_bank_override(db: AsyncSession, tenant_id: str | None,
                                 databank_id: str | None) -> str | None:
    """Explicit bank choice (playground/tests): use it only when the tenant
    owns it. Anything else is ignored loudly in the log — never an error
    to the caller, and never another tenant's bank."""
    if not databank_id or not tenant_id:
        return None
    try:
        from sqlalchemy import select

        from ..rag.models import Databank

        async with db.begin_nested():
            row = (
                await db.execute(
                    select(Databank.id).where(
                        Databank.id == databank_id,
                        Databank.user_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
        if not row:
            logger.warning("Bank override %s not owned by tenant; ignoring",
                           databank_id)
            return None
        return row
    except Exception as e:
        logger.debug("Bank override lookup failed: %s", e)
        return None


async def _resolve_reply_prefs(req: ReviewEngineRequest, tenant_id: str, db: AsyncSession) -> dict:
    """Dialect, language policy, and promo flags for this generation.

    Priority: explicit request override, else the channel's auto-reply
    config, else safe defaults (auto/match, all promo OFF).
    """
    from sqlalchemy import select

    prefs: dict = {
        "dialect": "auto",
        "reply_language": "match",
        "promo_product_mentions": False,
        "promo_links": False,
        "promo_only_relevant": True,
        "promo_max_ctas": 1,
    }
    if req.dialect:
        from .dialects import is_valid_dialect_db

        if not await is_valid_dialect_db(req.dialect, db):
            raise ValueError(f"Unknown dialect '{req.dialect}'.")
        prefs["dialect"] = req.dialect
    if req.reply_language:
        prefs["reply_language"] = req.reply_language
    if req.channel_id:
        from ..channels.models import AutoReplyConfig, Channel

        # Ownership-checked: a tenant passing another tenant's channel_id
        # must NOT inherit their dialect/promo settings (P0 cross-tenant
        # fix). Unowned channel → safe defaults, loudly logged.
        cfg = (
            await db.execute(
                select(AutoReplyConfig).join(
                    Channel, Channel.id == AutoReplyConfig.channel_id
                ).where(
                    AutoReplyConfig.channel_id == req.channel_id,
                    Channel.user_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if cfg is None:
            logger.warning("Reply-prefs channel %s not owned by tenant; using defaults",
                           req.channel_id)
        else:
            if not req.dialect and (cfg.dialect or "auto") != "auto":
                prefs["dialect"] = cfg.dialect
            if not req.reply_language and (cfg.reply_language or "match") != "match":
                prefs["reply_language"] = cfg.reply_language
            prefs["promo_product_mentions"] = bool(cfg.promo_product_mentions)
            prefs["promo_links"] = bool(cfg.promo_links)
            prefs["promo_only_relevant"] = (
                True if cfg.promo_only_relevant is None else bool(cfg.promo_only_relevant)
            )
            prefs["promo_max_ctas"] = (
                cfg.promo_max_ctas if cfg.promo_max_ctas is not None else 1
            )
    return prefs


def marketing_requirements(prefs: dict) -> list[str]:
    """Binding requirements for merchant-opted-in promotion.

    Empty when everything is off (historical no-promo behavior unchanged).
    Relevance gating itself lives in the offer/product machinery; these
    lines only grant permission and the CTA cap.
    """
    reqs: list[str] = []
    if prefs.get("promo_product_mentions"):
        line = (
            "Promotional product mentions are ALLOWED for this merchant: you may "
            "name a relevant product/service by its exact name when it fits naturally."
        )
        if prefs.get("promo_only_relevant", True):
            line += " Only when directly relevant to what the reviewer wrote — never pitch unprompted."
        reqs.append(line)
    if prefs.get("promo_links"):
        max_ctas = prefs.get("promo_max_ctas", 1)
        line = (
            "Promotional links are ALLOWED: you may include at most "
            f"{max_ctas} link(s), and ONLY a URL that appears verbatim in "
            "Business Context — never invent one."
        )
        if prefs.get("promo_only_relevant", True):
            line += " Only when directly relevant to what the reviewer wrote."
        reqs.append(line)
    return reqs


def build_requirements(
    analysis: ReviewAnalysis,
    issues: list[ExtractedIssue],
    strategies: list[StrategyMatch],
    suppressed: list[SuppressedStrategy],
    tier: dict | None = None,
    business_context: str | None = None,
) -> list[str]:
    """Binding generation requirements from issues + eligible strategies."""
    reqs: list[str] = []
    if tier:
        reqs.append(
            f"Reply MUST fit {tier['max_sentences']} sentences / ~{tier['min_words']}-{tier['max_words']} words. "
            f"Compress all strategies into this budget — one sentence may satisfy several strategies. "
            f"Maximize specificity per word; cut every sentence that adds no new information."
        )
    for s in strategies:
        if s.strategy_id in BEST_EFFORT:
            reqs.append(f"{s.name} is BEST-EFFORT: include only if natural within budget — never pad the reply for it.")
    for issue in issues:
        reqs.append(
            f"Address the {issue.label.lower()} ({issue.detail}) in natural customer-facing words — "
            f"internal labels stay internal, never in the reply."
        )
    for s in strategies:
        if s.strategy_id == "address_specific_issue" and issues:
            reqs.append("Name each concrete complaint fact; do not summarize them away.")
        if s.conditional and s.condition_note:
            reqs.append(f"{s.name}: {s.condition_note}")
        if s.strategy_id == "mention_relevant_offer":
            reqs.append(
                "Any offer mentioned must use EXACT verified terms from Business Context — "
                "never invent or modify price, discount %, duration, eligibility, or terms. "
                "Keep it to one brief clause, not a sales pitch."
            )
    for sp in suppressed:
        reqs.append(f"DO NOT execute '{sp.name}': {sp.reason}")
    deferred_names = [s.name for s in suppressed if s.reason.startswith("Deferred")]
    if deferred_names:
        reqs.append(
            "These eligible strategies were deliberately left out to keep the reply short — "
            f"do NOT work them in: {', '.join(deferred_names)}."
        )
    reqs.append(
        "No invented operational claims (training, refunds, investigations, manager contact, "
        "policy changes, overhauls, never-again promises) unless stated in Business Context."
    )
    if "question" in (analysis.intent or []):
        # A question-review is an inquiry, not feedback — thanking it for a
        # "wonderful review" is nonsense, and without verified facts the
        # reply must not invent products, menus, prices or availability.
        if (business_context or "").strip():
            reqs.append(
                "The review is a QUESTION, not feedback: answer it directly and ONLY from "
                "Business Context. Do NOT thank the reviewer for their review or rating and "
                "do not praise their feedback. Never state products, availability, prices or "
                "hours that Business Context does not confirm."
            )
        else:
            reqs.append(
                "The review is a QUESTION, not feedback: never thank the reviewer for their "
                "review or rating, and never praise their feedback. Business Context has no "
                "verified answer: do NOT invent products, menus, prices, availability or any "
                "operational fact — say the team will follow up with accurate details and "
                "invite them to visit or contact the business."
            )
    reqs.append(
        "Customer-facing copy only: no internal labels, snake_case terms, strategy names, "
        "or classification vocabulary anywhere in the reply."
    )
    has_pricing = any(i.key == "pricing" for i in issues)
    has_billing = any(i.key == "billing" for i in issues) or (analysis.issue_type or "") == "billing"
    if has_pricing and not has_billing:
        reqs.append(
            "PRICING concern (too expensive), NOT a billing error — address value perception empathetically. "
            "Never use refund/charge/invoice/payment-failure language."
        )
    if analysis.sentiment in ("very_negative", "negative"):
        reqs.append("Match the gravity of a negative review — no dismissive or breezy tone.")
    return reqs


async def _channel_databank_id(channel_id: str | None, tenant_id: str, db: AsyncSession) -> str | None:
    """The databank linked to this channel in Automations (if any)."""
    if not channel_id:
        return None
    try:
        from sqlalchemy import select

        from ..channels.models import AutoReplyConfig, Channel

        ch = (
            await db.execute(
                select(Channel.id).where(Channel.id == channel_id, Channel.user_id == tenant_id)
            )
        ).scalar_one_or_none()
        if not ch:
            return None
        return (
            await db.execute(
                select(AutoReplyConfig.databank_id).where(AutoReplyConfig.channel_id == channel_id)
            )
        ).scalar_one_or_none()
    except Exception as e:
        logger.warning("Channel databank lookup failed: %s", e)
        return None


async def _gather_evidence(needs, tenant_id: str | None, channel_id: str | None,
                     db: AsyncSession, bank_id: str | None = None):
    """Fulfill evidence needs via the Retrieval Layer.

    Returns (context_parts, has_offer_data, offer_texts, has_product_data,
    calls). context_parts are rendered facts-only strings — no mechanism
    names, no origins. calls are audit entries (need kind + fact count).
    """
    from ..retrieval.evidence import NEED_OFFER, NEED_PRODUCT

    context_parts: list[str] = []
    calls: list[ToolCall] = []
    has_offer_data = False
    has_product_data = False
    offer_texts: list[str] = []
    if not needs or not tenant_id:
        return context_parts, has_offer_data, offer_texts, has_product_data, calls
    results = await retrieve_evidence(
        needs, tenant_id=tenant_id, channel_id=channel_id, db=db,
        bank_id=bank_id,
    )
    for need in needs:
        res = results.get(need.kind)
        if res is None or not res.has_data:
            continue
        context_parts.append(res.rendered)
        calls.append(ToolCall(
            tool=f"evidence:{need.kind}",
            args={"query": need.query},
            result_summary=f"{len(res.items)} fact(s)",
        ))
        if need.kind == NEED_OFFER:
            has_offer_data = True
            offer_texts.extend(res.facts[:5])
        if need.kind == NEED_PRODUCT:
            has_product_data = True
    return context_parts, has_offer_data, offer_texts, has_product_data, calls


async def process_review(
    req: ReviewEngineRequest,
    tenant_id: str,
    db: AsyncSession,
) -> ReviewEngineResponse:
    """Full agent loop: understand -> decide tools -> call tools -> strategies -> generate -> validate -> log."""
    t0 = time.monotonic()
    log_id = str(uuid.uuid4())

    # Resolve model: explicit override, else the channel's Automations model.
    # Raises ValueError if none configured. No silent defaults.
    model, model_source = await _resolve_engine_model(req, tenant_id, db)
    logger.info("Review engine using model %s (source: %s)", model, model_source)

    # Resolve reply prefs (dialect, language policy, promo flags).
    prefs = await _resolve_reply_prefs(req, tenant_id, db)
    if prefs["dialect"] != "auto":
        from .dialects import get_dialect

        # Deleted codes fall back to auto — never break generation.
        dialect_entry: dict | None = await get_dialect(prefs["dialect"], db)
    else:
        dialect_entry = None

    # Channel's linked databank (Automations), unless the request carries
    # an explicit owned-bank override (playground/tests).
    channel_bank = await _channel_databank_id(req.channel_id, tenant_id, db)
    channel_bank = (
        await _resolve_bank_override(db, tenant_id, req.databank_id)
        or channel_bank
    )

    # Step 1: Analyze review (errors propagate — no rule-based cover-up)
    analysis, analysis_stats = await analyze_review(req.review_text, req.rating, req.reviewer_name, model,
                                                       tenant_id=tenant_id, channel_id=req.channel_id)

    # Step 2: Extract concrete complaint facts (deterministic)
    issues = extract_issues(req.review_text, analysis)

    # Step 3: Search strategies, then resolve conflicts (eligibility gating)
    matched = await search_strategies(analysis, req.channel, db)
    strategies, suppressed = resolve_strategy_conflicts(matched, analysis, req.review_text)

    # Step 4: Strategy-declared evidence, fulfilled by the Retrieval Layer.
    # Owner identity first — retrieved evidence corroborates it.
    try:
        _identity = await _layer_identity(db, tenant_id, req.channel_id)
    except Exception:
        _identity = ""
    needs = evidence_needs_for(analysis, strategies)
    (evidence_parts, has_offer_data, offer_texts, has_product_data,
     evidence_calls) = await _gather_evidence(
        needs, tenant_id, req.channel_id, db, bank_id=channel_bank)
    business_context_parts: list[str] = ([_identity] if _identity else []) + evidence_parts
    all_tool_calls: list[ToolCall] = []
    all_tool_calls.extend(evidence_calls)

    business_context = "\n".join(business_context_parts) if business_context_parts else None

    # Step 4b: Business relevance — flag reviews about something else.
    # Assessed after retrieval so databank hits corroborate relevance.
    # Complaint topics count too: "cold food" fires without a product ref.
    domain = await resolve_business_domain(req.channel_id, tenant_id, db)
    relevance = RelevanceVerdict(**apply_retrieval_corroboration(
        assess_relevance(req.review_text, analysis, domain, issues), has_product_data))
    if relevance.verdict == "off_topic":
        logger.info("Review flagged off-topic: %s", relevance.reason)

    # Step 5: Prune unsatisfiable strategies BEFORE generation.
    # A strategy whose hard dependency came back empty — or whose offer
    # doesn't match the mentioned product — is removed here.
    strategies, suppressed = prune_unsatisfiable(
        strategies, suppressed,
        has_offer_data=has_offer_data, has_product_data=has_product_data,
        product_ref=analysis.product_reference, offer_texts=offer_texts,
    )

    # Step 5b: Select the MINIMAL execution set. Eligible ≠ executed:
    # deferred strategies are allowed but add no customer value in budget.
    strategies, suppressed = select_execution_set(
        strategies, suppressed, analysis, issues, req.review_text,
    )

    # Step 6: Length tier + binding generation requirements (final set)
    tier = select_tier(req.rating, analysis, req.review_text, n_issues=len(issues))
    requirements = build_requirements(analysis, issues, strategies, suppressed, tier, business_context)
    if (req.previous_draft or "").strip():
        requirements.append(
            "The merchant REJECTED this previous draft: "
            f"\"{req.previous_draft.strip()[:400]}\" — write a clearly different reply; "
            "do not reuse its wording, opening line or structure."
        )
    if relevance.verdict == "off_topic":
        requirements.append(
            "Possible off-topic review: do NOT discuss, apologize for, or make claims about "
            "the specific mentioned item — keep the reply general and brief. If it is phrased "
            "as a question about something the business does not offer (see the identity block), "
            "answer NO plainly in one clause and point at what the business DOES offer instead."
        )
    requirements.extend(marketing_requirements(prefs))

    # Step 4: Get channel policy + brand voice
    channel_policy = CHANNEL_POLICIES.get(req.channel, CHANNEL_POLICIES["google_review"])
    brand_voice = DEFAULT_BRAND_VOICE

    # Close DB before LLM generation to free connection for other requests
    await db.close()

    # Step 6: Generate + validate loop (same model, up to MAX_TOOL_ROUNDS tries).
    # Generation errors propagate — no fallback models, no template replies.
    # Each retry receives the previous validation failures so it can fix them.
    generated: GeneratedResponse | None = None
    validation: ValidationResult | None = None
    gen_stats = {"model": model, "tokens": 0, "latency_ms": 0}
    previous_issues: list[str] | None = None
    suppressed_ids = [s.strategy_id for s in suppressed]
    promo_cap = (
        prefs["promo_max_ctas"]
        if (prefs["promo_links"] or prefs["promo_product_mentions"])
        else None
    )

    for iteration in range(MAX_TOOL_ROUNDS):
        generated, gen_stats = await generate_response(
            analysis=analysis,
            strategies=strategies,
            channel_policy=channel_policy,
            brand_voice=brand_voice,
            business_context=business_context,
            model=model,
            issues=issues,
            requirements=requirements,
            previous_issues=previous_issues,
            tier=tier,
            tenant_id=tenant_id,
            channel_id=req.channel_id,
            review_text=req.review_text,
            dialect=dialect_entry,
            reply_language=prefs["reply_language"],
        )

        # Validate against the REVIEW (issues, fulfillment), not just the response
        validation = validate_response(
            generated, analysis, channel_policy,
            review_text=req.review_text, issues=issues,
            active_strategies=strategies, suppressed_ids=suppressed_ids,
            tier=tier, business_context=business_context,
            has_offer_data=has_offer_data, rating=req.rating,
            promo_max_ctas=promo_cap,
        )

        if validation.passed:
            break

        logger.info("Validation failed (attempt %d/%d): %s", iteration + 1, MAX_TOOL_ROUNDS, validation.issues)
        previous_issues = list(validation.issues)
        if iteration == MAX_TOOL_ROUNDS - 1:
            validation.regenerated = True

    # Reopen DB session for logging
    async with _async_session() as write_db:
        # Step 7: Log (full pipeline artifacts for debugging)
        total_latency = int((time.monotonic() - t0) * 1000)
        token_in = analysis_stats.get("tokens", 0) + gen_stats.get("tokens", 0)

        # Off-topic reviews are always flagged for human review — even when
        # the reply itself is valid. No extra regen attempts are burned.
        final_status = "approved" if validation.passed else "needs_review"
        if relevance.verdict == "off_topic":
            final_status = "needs_review"
            validation.issues.append(
                f"Flagged: review might be irrelevant to this business ({relevance.reason}). "
                f"Queued for human review."
            )

        log_entry = ReviewResponseLog(
            id=log_id,
            tenant_id=tenant_id,
            channel_id=req.channel_id,
            review_id=req.review_id,
            review_text=req.review_text[:2000] if req.review_text else None,
            rating=req.rating,
            reviewer_name=req.reviewer_name,
            channel=req.channel,
            analysis=analysis.model_dump(),
            selected_strategies=[s.model_dump() for s in strategies],
            tool_calls=[tc.model_dump() for tc in all_tool_calls] or None,
            retrieved_offers={
                "issues": [i.model_dump() for i in issues],
                "suppressed": [s.model_dump() for s in suppressed],
                "requirements": requirements,
                "tier": tier,
                "relevance": relevance.model_dump(),
            },
            generated_response=generated.response_text,
            validation_result=validation.model_dump(),
            status=final_status,
            model=model,
            token_input=token_in,
            token_output=gen_stats.get("tokens", 0),
            latency_ms=total_latency,
        )
        write_db.add(log_entry)
        await write_db.commit()

    return ReviewEngineResponse(
        response_text=generated.response_text,
        strategies_used=generated.strategies_used,
        validation=validation,
        analysis=analysis,
        model=model,
        latency_ms=total_latency,
        log_id=log_id,
        status=final_status,
        relevance=relevance,
    )


# ── Streaming version ────────────────────────────────────

async def process_review_stream(
    req: ReviewEngineRequest,
    tenant_id: str,
    db: AsyncSession,
) -> AsyncGenerator[dict, None]:
    """Yield SSE progress events while processing a review."""
    t0 = time.monotonic()
    log_id = str(uuid.uuid4())

    model, model_source = await _resolve_engine_model(req, tenant_id, db)
    logger.info("Review engine (stream) using model %s (source: %s)", model, model_source)
    prefs = await _resolve_reply_prefs(req, tenant_id, db)
    if prefs["dialect"] != "auto":
        from .dialects import get_dialect as _get_dialect

        dialect_entry: dict | None = await _get_dialect(prefs["dialect"], db)
    else:
        dialect_entry = None
    channel_bank = await _channel_databank_id(req.channel_id, tenant_id, db)
    channel_bank = (
        await _resolve_bank_override(db, tenant_id, req.databank_id)
        or channel_bank
    )
    yield {"step": "analyzing", "message": f"Analyzing with {model}...", "progress": 10, "model": model, "model_source": model_source}

    # Step 1: Analyze (errors propagate — surfaced as an SSE error event)
    analysis, analysis_stats = await analyze_review(req.review_text, req.rating, req.reviewer_name, model,
                                                       tenant_id=tenant_id, channel_id=req.channel_id)
    yield {"step": "analyzed", "message": f"Detected: {analysis.sentiment}, {analysis.emotion}, intent={analysis.intent}", "analysis": analysis.model_dump(), "progress": 25}

    # Step 2: Extract issues + resolve strategy conflicts
    issues = extract_issues(req.review_text, analysis)
    yield {"step": "issues", "message": f"Extracted {len(issues)} concrete fact(s).",
           "issues": [i.model_dump() for i in issues], "progress": 28}

    # Step 3: Strategies (match → resolve eligibility)
    yield {"step": "strategies", "message": "Searching relevant response strategies...", "progress": 30}
    matched = await search_strategies(analysis, req.channel, db)
    strategies, suppressed = resolve_strategy_conflicts(matched, analysis, req.review_text)
    for s in strategies:
        yield {"step": "strategy", "strategy": {"id": s.strategy_id, "name": s.name, "reason": s.reason, "priority": s.priority, "conditional": s.conditional, "condition_note": s.condition_note}, "progress": 35}
    for sp in suppressed:
        yield {"step": "strategy_suppressed", "strategy": sp.model_dump(), "progress": 36}

    # Step 4: Strategy-declared evidence via the Retrieval Layer
    yield {"step": "retrieval", "message": "Gathering business evidence for the selected strategies...", "progress": 40, "bank_id": channel_bank}
    needs = evidence_needs_for(analysis, strategies)
    # Owner identity first — retrieved evidence corroborates it.
    try:
        _identity = await _layer_identity(db, tenant_id, req.channel_id)
    except Exception:
        _identity = ""
    business_context_parts: list[str] = [_identity] if _identity else []
    all_tool_calls: list[ToolCall] = []

    evidence_results = await retrieve_evidence(
        needs, tenant_id=tenant_id, channel_id=req.channel_id, db=db,
        bank_id=channel_bank,
    )
    from ..retrieval.evidence import NEED_OFFER, NEED_PRODUCT

    has_offer_data = False
    has_product_data = False
    offer_texts: list[str] = []
    for need in needs:
        yield {"step": "evidence", "need": need.kind, "query": need.query, "progress": 50}
        res = evidence_results.get(need.kind)
        count = len(res.items) if res else 0
        if res and res.has_data:
            business_context_parts.append(res.rendered)
            all_tool_calls.append(ToolCall(
                tool=f"evidence:{need.kind}",
                args={"query": need.query},
                result_summary=f"{count} fact(s)",
            ))
            if need.kind == NEED_OFFER:
                has_offer_data = True
                offer_texts.extend(res.facts[:5])
            if need.kind == NEED_PRODUCT:
                has_product_data = True
        yield {"step": "evidence_result", "need": need.kind,
               "result": json.dumps({"count": count}), "progress": 60}

    business_context = "\n".join(business_context_parts) if business_context_parts else None

    # Step 4b: Business relevance (after retrieval so hits corroborate).
    domain = await resolve_business_domain(req.channel_id, tenant_id, db)
    relevance = RelevanceVerdict(**apply_retrieval_corroboration(
        assess_relevance(req.review_text, analysis, domain, issues), has_product_data))
    if relevance.verdict == "off_topic":
        logger.info("Review (stream) flagged off-topic: %s", relevance.reason)
    yield {"step": "relevance", "message": f"Relevance: {relevance.verdict}.",
           "relevance": relevance.model_dump(), "progress": 61}

    # Step 5: Prune unsatisfiable strategies, then select minimal set
    n_suppressed_before = len(suppressed)
    strategies, suppressed = prune_unsatisfiable(
        strategies, suppressed,
        has_offer_data=has_offer_data, has_product_data=has_product_data,
        product_ref=analysis.product_reference, offer_texts=offer_texts,
    )
    strategies, suppressed = select_execution_set(
        strategies, suppressed, analysis, issues, req.review_text,
    )
    for sp in suppressed[n_suppressed_before:]:
        step = "strategy_deferred" if sp.reason.startswith("Deferred") else "strategy_suppressed"
        yield {"step": step, "strategy": sp.model_dump(), "progress": 62}
    tier = select_tier(req.rating, analysis, req.review_text, n_issues=len(issues))
    requirements = build_requirements(analysis, issues, strategies, suppressed, tier, business_context)
    if (req.previous_draft or "").strip():
        requirements.append(
            "The merchant REJECTED this previous draft: "
            f"\"{req.previous_draft.strip()[:400]}\" — write a clearly different reply; "
            "do not reuse its wording, opening line or structure."
        )
    if relevance.verdict == "off_topic":
        requirements.append(
            "Possible off-topic review: do NOT discuss, apologize for, or make claims about "
            "the specific mentioned item — keep the reply general and brief. If it is phrased "
            "as a question about something the business does not offer (see the identity block), "
            "answer NO plainly in one clause and point at what the business DOES offer instead."
        )
    requirements.extend(marketing_requirements(prefs))
    yield {"step": "requirements", "message": f"{len(requirements)} binding generation requirement(s).",
            "requirements": requirements, "tier": tier, "progress": 65}

    # Step 4: Generate
    channel_policy = CHANNEL_POLICIES.get(req.channel, CHANNEL_POLICIES["google_review"])
    brand_voice = DEFAULT_BRAND_VOICE

    # Close DB before LLM generation to free connection for other requests
    await db.close()

    yield {"step": "generating", "message": "Generating response...", "progress": 70}

    generated: GeneratedResponse | None = None
    validation: ValidationResult | None = None
    gen_stats = {"model": model, "tokens": 0, "latency_ms": 0}
    previous_issues: list[str] | None = None
    suppressed_ids = [s.strategy_id for s in suppressed]
    promo_cap = (
        prefs["promo_max_ctas"]
        if (prefs["promo_links"] or prefs["promo_product_mentions"])
        else None
    )

    for iteration in range(MAX_TOOL_ROUNDS):
        generated, gen_stats = await generate_response(
            analysis=analysis, strategies=strategies,
            channel_policy=channel_policy, brand_voice=brand_voice,
            business_context=business_context, model=model,
            issues=issues, requirements=requirements,
            previous_issues=previous_issues, tier=tier,
            tenant_id=tenant_id, channel_id=req.channel_id,
            review_text=req.review_text,
            dialect=dialect_entry,
            reply_language=prefs["reply_language"],
        )

        validation = validate_response(
            generated, analysis, channel_policy,
            review_text=req.review_text, issues=issues,
            active_strategies=strategies, suppressed_ids=suppressed_ids,
            tier=tier, business_context=business_context,
            has_offer_data=has_offer_data, rating=req.rating,
            promo_max_ctas=promo_cap,
        )
        yield {"step": "fulfillment", "message": f"Validation attempt {iteration + 1}: {'passed' if validation.passed else 'failed'}.",
                "fulfillment": [f.model_dump() for f in validation.strategy_fulfillment],
                "claims": [c.model_dump() for c in validation.claim_verdicts],
                "checks": validation.checks, "validation_issues": validation.issues, "progress": 80}
        if validation.passed:
            break
        previous_issues = list(validation.issues)
        if iteration == MAX_TOOL_ROUNDS - 1:
            validation.regenerated = True

    yield {"step": "validating", "message": "Validating response against policies...", "progress": 85}

    # Reopen DB session for logging
    async with _async_session() as write_db:
        total_latency = int((time.monotonic() - t0) * 1000)
        final_status = "approved" if validation.passed else "needs_review"
        if relevance.verdict == "off_topic":
            final_status = "needs_review"
            validation.issues.append(
                f"Flagged: review might be irrelevant to this business ({relevance.reason}). "
                f"Queued for human review."
            )
        log_entry = ReviewResponseLog(
            id=log_id, tenant_id=tenant_id, channel_id=req.channel_id,
            review_id=req.review_id, review_text=req.review_text[:2000] if req.review_text else None,
            rating=req.rating, reviewer_name=req.reviewer_name, channel=req.channel,
            analysis=analysis.model_dump(), selected_strategies=[s.model_dump() for s in strategies],
            tool_calls=[tc.model_dump() for tc in all_tool_calls] or None,
            retrieved_offers={
                "issues": [i.model_dump() for i in issues],
                "suppressed": [s.model_dump() for s in suppressed],
                "requirements": requirements,
                "tier": tier,
                "relevance": relevance.model_dump(),
            },
            generated_response=generated.response_text, validation_result=validation.model_dump(),
            status=final_status, model=model,
            token_input=analysis_stats.get("tokens", 0) + gen_stats.get("tokens", 0),
            token_output=gen_stats.get("tokens", 0), latency_ms=total_latency,
        )
        write_db.add(log_entry)
        await write_db.commit()

    # Final event
    yield {
        "step": "done",
        "message": "Response needs review" if final_status == "needs_review" else "Response ready",
        "progress": 100,
        "response": {
            "response_text": generated.response_text,
            "strategies_used": generated.strategies_used,
            "validation": validation.model_dump(),
            "analysis": analysis.model_dump(),
            "model": model,
            "latency_ms": total_latency,
            "log_id": log_id,
            "status": final_status,
            "relevance": relevance.model_dump(),
        },
    }
