"""Review engine orchestrator — the agent loop with tool calling."""
import json
import logging
import time
import uuid
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.providers.base import LLMMessage, LLMRequest, ProviderError
from ..llm.providers.registry import get_provider_for_model
from ..llm.service import _resolve_model
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
    prune_unsatisfiable,
    resolve_strategy_conflicts,
    search_strategies,
    select_execution_set,
)
from .tools import TOOL_DEFINITIONS, TOOL_MAP
from .understanding import analyze_review
from .validator import select_tier, validate_response

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3


async def _resolve_engine_model(req: ReviewEngineRequest, tenant_id: str, db: AsyncSession) -> tuple[str, str]:
    """Resolve which model the engine must use. Returns (model_id, source).

    Priority:
      1. Explicit `model` in the request (playground / API override).
      2. The channel's auto-reply config model — what Automations saves.

    No silent defaults, no fallback models. If neither is set, raises
    ValueError telling the user to pick a reply model in Automations.
    """
    from sqlalchemy import select

    if req.model:
        return req.model, "request"

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
            return cfg, "channel"

    raise ValueError(
        "No reply model configured for this channel. "
        "Select a reply model in Automations for this location."
    )


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
    if "question" in (analysis.intent or []) and not (business_context or "").strip():
        reqs.append(
            "The customer asks WHY — Business Context has no verified reason: "
            "acknowledge the concern WITHOUT inventing an explanation. "
            "No pricing rationale, ingredient stories, or process descriptions."
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


async def _call_tool(
    tool_name: str,
    args: dict,
    tenant_id: str,
    db: AsyncSession,
    databank_id: str | None = None,
) -> str:
    """Execute a tool and return its result as a JSON string."""
    tool_fn = TOOL_MAP.get(tool_name)
    if not tool_fn:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})

    try:
        result = await tool_fn(**args, tenant_id=tenant_id, db=db, databank_id=databank_id)
        return json.dumps(result, default=str)
    except TypeError as e:
        # Some tools don't need tenant_id/db — try without
        try:
            clean_args = {k: v for k, v in args.items() if k not in ("tenant_id", "db")}
            result = await tool_fn(**clean_args)
            return json.dumps(result, default=str)
        except Exception:
            return json.dumps({"error": str(e)})
    except Exception as e:
        logger.error("Tool %s failed: %s", tool_name, e)
        return json.dumps({"error": str(e)})


def _tools_prompt() -> str:
    """Render the full tool schemas for the decision prompt.

    The model sees exact parameter names/types — it must never invent args.
    """
    import json as _json

    lines = []
    for t in TOOL_DEFINITIONS:
        lines.append(f"- {t['name']}: {t['description']}\n  args: {_json.dumps(t['parameters'])}")
    return "\n".join(lines)


async def _decide_tools(
    analysis: ReviewAnalysis,
    strategies: list,
    model: str,
    tenant_id: str | None = None,
    channel_id: str | None = None,
) -> list[dict]:
    """Ask the LLM which tools to call based on review analysis. Returns list of {tool, args}."""
    provider = get_provider_for_model(model)
    api_model, _ = _resolve_model(model)

    system = f"""You are a tool selection engine. Given a review analysis, decide which tools to call.

Available tools (use EXACT parameter names — never invent arguments):
{_tools_prompt()}

Rules:
- Only call tools that are genuinely needed for this review.
- For positive/neutral reviews with no specific product mentioned, call NO tools.
- If a product is mentioned (product_reference present) and a recommendation strategy is possible, call search_products with that product name to verify what else the business offers — the planner will decide whether to mention it.
- For billing/refund complaints, do NOT call find_offers unless the customer explicitly asks for compensation, a discount, or a deal.
- Call find_offers ONLY when the customer explicitly asks for compensation, a discount, or a deal — OR when there is a pricing complaint (too expensive) about a mentioned product, to verify whether a matching offer exists. The planner decides separately whether to mention it.
- The injected tenant_id/db are handled automatically — never include them in args.
- Return a JSON array of tool calls. Each: {{"tool": "name", "args": {{...}}}}
- If no tools needed, return an empty array: []
- Return ONLY the JSON array. No explanation."""

    user_msg = f"Review analysis:\n{json.dumps(analysis.model_dump(), indent=2)}"

    try:
        resp = await provider.complete(
            LLMRequest(
                model=api_model,
                messages=[LLMMessage(role="user", content=user_msg)],
                system_prompt=system,
                temperature=0.1,
                max_tokens=200,
                stream=False,
                tenant_id=tenant_id,
                model_id=model,
                purpose="review_engine.tools",
                channel_id=channel_id,
            )
        )
    except ProviderError:
        return []

    raw = resp.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        calls = json.loads(raw)
        if not isinstance(calls, list):
            calls = []
        else:
            calls = [c for c in calls if isinstance(c, dict) and "tool" in c]
    except json.JSONDecodeError:
        calls = []

    # Deterministic fallback: positive mention with conditional recommend must verify inventory.
    # The LLM sometimes skips tools for happy reviews — ensure we look up the product.
    product_ref = (analysis.product_reference or "").strip() if hasattr(analysis, "product_reference") else ""
    is_positive = getattr(analysis, "sentiment", "") in ("positive", "very_positive")
    needs_product_check = is_positive and product_ref and any(
        getattr(s, "strategy_id", "") == "recommend_related_product" for s in strategies
    )
    if needs_product_check and not any(c.get("tool") == "search_products" for c in calls):
        # Also handle stale arg name "keyword" → correct to "query"
        calls.append({"tool": "search_products", "args": {"query": product_ref}})
    # Normalize any stale "keyword" arg the model might still emit
    for c in calls:
        if c.get("tool") == "search_products" and "keyword" in (c.get("args") or {}):
            args = dict(c["args"])
            args["query"] = args.pop("keyword")
            c["args"] = args
    return calls


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

    # Channel's linked databank (Automations) — tools search here first.
    channel_bank = await _channel_databank_id(req.channel_id, tenant_id, db)

    # Step 1: Analyze review (errors propagate — no rule-based cover-up)
    analysis, analysis_stats = await analyze_review(req.review_text, req.rating, req.reviewer_name, model,
                                                       tenant_id=tenant_id, channel_id=req.channel_id)

    # Step 2: Extract concrete complaint facts (deterministic)
    issues = extract_issues(req.review_text, analysis)

    # Step 3: Search strategies, then resolve conflicts (eligibility gating)
    matched = await search_strategies(analysis, req.channel, db)
    strategies, suppressed = resolve_strategy_conflicts(matched, analysis, req.review_text)

    # Step 4: Decide + call tools (the AI decides what data it needs)
    all_tool_calls: list[ToolCall] = []
    business_context_parts: list[str] = []
    has_offer_data = False
    has_product_data = False
    offer_texts: list[str] = []

    tool_decisions = await _decide_tools(analysis, strategies, model,
                                         tenant_id=tenant_id, channel_id=req.channel_id)

    for td in tool_decisions[:MAX_TOOL_ROUNDS]:
        tool_name = td["tool"]
        args = td.get("args", {})
        result_json = await _call_tool(tool_name, args, tenant_id, db, databank_id=channel_bank)

        all_tool_calls.append(ToolCall(
            tool=tool_name,
            args=args,
            result_summary=result_json[:500],
        ))

        # Parse result for context
        try:
            result_data = json.loads(result_json)
            if result_data.get("results"):
                business_context_parts.append(
                    f"[{tool_name}] {json.dumps(result_data['results'][:3], default=str)}"
                )
                if tool_name == "find_offers":
                    has_offer_data = True
                    offer_texts.extend(str(r) for r in result_data["results"][:5])
                if tool_name in ("search_products", "get_product"):
                    has_product_data = True
        except json.JSONDecodeError:
            pass

    business_context = "\n".join(business_context_parts) if business_context_parts else None

    # Step 4b: Business relevance — flag reviews about something else.
    # Assessed after retrieval so databank hits corroborate relevance.
    domain = await resolve_business_domain(req.channel_id, tenant_id, db)
    relevance = RelevanceVerdict(**apply_retrieval_corroboration(
        assess_relevance(req.review_text, analysis, domain), has_product_data))
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
    if relevance.verdict == "off_topic":
        requirements.append(
            "Possible off-topic review: do NOT discuss, apologize for, or make claims about "
            "the specific mentioned item — keep the reply general and brief."
        )

    # Step 4: Get channel policy + brand voice
    channel_policy = CHANNEL_POLICIES.get(req.channel, CHANNEL_POLICIES["google_review"])
    brand_voice = DEFAULT_BRAND_VOICE

    # Step 6: Generate + validate loop (same model, up to MAX_TOOL_ROUNDS tries).
    # Generation errors propagate — no fallback models, no template replies.
    # Each retry receives the previous validation failures so it can fix them.
    generated: GeneratedResponse | None = None
    validation: ValidationResult | None = None
    gen_stats = {"model": model, "tokens": 0, "latency_ms": 0}
    previous_issues: list[str] | None = None
    suppressed_ids = [s.strategy_id for s in suppressed]

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
        )

        # Validate against the REVIEW (issues, fulfillment), not just the response
        validation = validate_response(
            generated, analysis, channel_policy,
            review_text=req.review_text, issues=issues,
            active_strategies=strategies, suppressed_ids=suppressed_ids,
            tier=tier, business_context=business_context,
            has_offer_data=has_offer_data, rating=req.rating,
        )

        if validation.passed:
            break

        logger.info("Validation failed (attempt %d/%d): %s", iteration + 1, MAX_TOOL_ROUNDS, validation.issues)
        previous_issues = list(validation.issues)
        if iteration == MAX_TOOL_ROUNDS - 1:
            validation.regenerated = True

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
    db.add(log_entry)
    await db.commit()

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
    channel_bank = await _channel_databank_id(req.channel_id, tenant_id, db)
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

    # Step 4: Tools
    yield {"step": "tools", "message": "Deciding which business data to retrieve...", "progress": 40}
    tool_decisions = await _decide_tools(analysis, strategies, model,
                                         tenant_id=tenant_id, channel_id=req.channel_id)
    business_context_parts: list[str] = []
    all_tool_calls: list[ToolCall] = []
    has_offer_data = False
    has_product_data = False
    offer_texts: list[str] = []

    for td in tool_decisions[:MAX_TOOL_ROUNDS]:
        tool_name = td["tool"]
        args = td.get("args", {})
        yield {"step": "tool_call", "tool": tool_name, "args": args, "progress": 50}
        result_json = await _call_tool(tool_name, args, tenant_id, db, databank_id=channel_bank)
        all_tool_calls.append(ToolCall(tool=tool_name, args=args, result_summary=result_json[:500]))
        try:
            result_data = json.loads(result_json)
            if result_data.get("results"):
                business_context_parts.append(f"[{tool_name}] {json.dumps(result_data['results'][:3], default=str)}")
                if tool_name == "find_offers":
                    has_offer_data = True
                    offer_texts.extend(str(r) for r in result_data["results"][:5])
                if tool_name in ("search_products", "get_product"):
                    has_product_data = True
        except json.JSONDecodeError:
            pass
        yield {"step": "tool_result", "tool": tool_name, "result": result_json[:300], "progress": 60}

    business_context = "\n".join(business_context_parts) if business_context_parts else None

    # Step 4b: Business relevance (after retrieval so hits corroborate).
    domain = await resolve_business_domain(req.channel_id, tenant_id, db)
    relevance = RelevanceVerdict(**apply_retrieval_corroboration(
        assess_relevance(req.review_text, analysis, domain), has_product_data))
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
    if relevance.verdict == "off_topic":
        requirements.append(
            "Possible off-topic review: do NOT discuss, apologize for, or make claims about "
            "the specific mentioned item — keep the reply general and brief."
        )
    yield {"step": "requirements", "message": f"{len(requirements)} binding generation requirement(s).",
           "requirements": requirements, "tier": tier, "progress": 65}

    # Step 4: Generate
    channel_policy = CHANNEL_POLICIES.get(req.channel, CHANNEL_POLICIES["google_review"])
    brand_voice = DEFAULT_BRAND_VOICE
    yield {"step": "generating", "message": "Generating response...", "progress": 70}

    generated: GeneratedResponse | None = None
    validation: ValidationResult | None = None
    gen_stats = {"model": model, "tokens": 0, "latency_ms": 0}
    previous_issues: list[str] | None = None
    suppressed_ids = [s.strategy_id for s in suppressed]

    for iteration in range(MAX_TOOL_ROUNDS):
        generated, gen_stats = await generate_response(
            analysis=analysis, strategies=strategies,
            channel_policy=channel_policy, brand_voice=brand_voice,
            business_context=business_context, model=model,
            issues=issues, requirements=requirements,
            previous_issues=previous_issues, tier=tier,
            tenant_id=tenant_id, channel_id=req.channel_id,
        )

        validation = validate_response(
            generated, analysis, channel_policy,
            review_text=req.review_text, issues=issues,
            active_strategies=strategies, suppressed_ids=suppressed_ids,
            tier=tier, business_context=business_context,
            has_offer_data=has_offer_data, rating=req.rating,
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

    # Step 7: Log (full pipeline artifacts for debugging)
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
    db.add(log_entry)
    await db.commit()

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
