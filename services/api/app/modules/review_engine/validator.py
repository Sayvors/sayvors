"""Validate generated responses: safety/policy + strategy fulfillment + quality.

Fulfillment answers "did the reply actually do what the selected strategies
require, against THIS review?" — each active strategy gets
{strategy, status, reason, evidence}. Any required failure fails the run.

Claim grounding: operational/business assertions must be review-grounded
(the customer said it) or business-grounded (databank context says it).
Everything else is an unsupported claim and fails.
"""
import logging
import re

from .claims import extract_claims, ground_claims
from .schemas import (
    ClaimVerdict,
    ExtractedIssue,
    GeneratedResponse,
    ReviewAnalysis,
    StrategyFulfillment,
    ValidationResult,
)

logger = logging.getLogger(__name__)

SENSITIVE_PATTERNS = [
    re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),           # phone numbers
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),  # emails
    re.compile(r"\b(order|invoice|#)\s*[A-Z0-9]{6,}\b", re.I),
    re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    re.compile(r"\b(IQ|SSN|NIN|ID)\s*[:#]?\s*\d{6,}\b", re.I),
]

HALLUCINATION_PATTERNS = [
    re.compile(r"(we have|we've|we |we |we )\s*(processed|completed|issued|issued)\s+(a |your )?(refund|return|credit|reimbursement)", re.I),
    re.compile(r"your (refund|return|order)\s+(has been|was|is)\s+(processed|completed|approved|issued|sent)", re.I),
    re.compile(r"\b(coupon|discount|promo)\s*code\s*[:=]?\s*\S+", re.I),
    re.compile(r"\brefund\b.*\b\d+", re.I),
]

INSTRUCTION_IGNORE_PATTERNS = [
    re.compile(r"(please|kindly)\s+(change|remove|update|delete)\s+(your\s+)?(review|rating|star)", re.I),
    re.compile(r"(we|our team)\s+(will|have)\s+(fix|repair|replace|resolve)\s+(the\s+)?(issue|problem)", re.I),
]

# ── Length tiers: internal complexity must compress into a short reply ──

def select_tier(
    rating: int | None,
    analysis: ReviewAnalysis,
    review_text: str,
    n_issues: int = 0,
) -> dict:
    """Targets, not rigid limits. Validator allows ~30% headroom.

    Complexity scales the budget: simple complaints stay short,
    multi-issue complaints get room — never padding.
    """
    rating = rating or 3
    is_question = "question" in (analysis.intent or []) or "?" in (review_text or "")
    if is_question:
        return {"label": "question", "max_sentences": 3, "max_words": 70, "min_words": 8}
    if rating <= 2 or analysis.sentiment in ("very_negative", "negative"):
        if n_issues <= 1 and len(review_text or "") < 150:
            return {"label": "simple-complaint", "max_sentences": 2, "max_words": 50, "min_words": 15}
        if n_issues <= 3:
            return {"label": "complaint", "max_sentences": 3, "max_words": 70, "min_words": 20}
        return {"label": "complex-complaint", "max_sentences": 4, "max_words": 90, "min_words": 25}
    if rating == 3:
        return {"label": "mixed", "max_sentences": 3, "max_words": 70, "min_words": 15}
    if rating == 4:
        return {"label": "positive", "max_sentences": 2, "max_words": 50, "min_words": 8}
    return {"label": "praise", "max_sentences": 2, "max_words": 40, "min_words": 6}


def count_words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def count_sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?…]+", text or "") if s.strip()])

# ── Claim grounding ──────────────────────────────────────
# (name, pattern, grounding stems that must appear in business context)

OPERATIONAL_CLAIMS: list[tuple[str, re.Pattern, list[str]]] = [
    ("staff training", re.compile(r"\b(retrain\w*|re-train\w*)\b", re.I), ["train"]),
    ("staff training program", re.compile(r"\btraining\b.{0,25}\b(staff|team|employee|crew)\b", re.I), ["train"]),
    ("investigation", re.compile(r"\binvestigat\w+", re.I), ["investigat"]),
    ("policy change", re.compile(r"\b(new policy|policy change|changed our polic|updated our polic)\b", re.I), ["polic"]),
    ("never-again promise", re.compile(r"\bnever happen again\b|\bwon't happen again\b|\bwill never\b.{0,25}\b(again|recur)\b", re.I), []),
    ("personnel action", re.compile(r"\b(terminated|fired|suspended|dismissed|reprimanded|let go)\b.{0,20}\b(staff|employee|waiter|server)\b", re.I), []),
    ("operational overhaul", re.compile(r"\b(overhaul\w*|revamp\w*|restructur\w*)\b", re.I), ["overhaul", "revamp"]),
    ("kitchen/process fix", re.compile(r"\b(improving|improved|upgraded|fixed|fixing)\s+(our\s+)?(kitchen|process|procedure|operation|recipe)\b", re.I), ["kitchen", "process"]),
    ("faster/hotter promise", re.compile(r"\b(faster|hotter|better|quicker)\s+(service|meals?|food|delivery)\b", re.I), []),
    ("manager will contact", re.compile(r"\b(manager|supervisor|owner)\s+(will|shall)\s+(contact|call|reach out|follow up)\b", re.I), ["manager", "contact"]),
    ("invented percentage", re.compile(r"\b\d{1,2}\s?%\s?(off|discount)\b", re.I), ["%", "percent", "discount", "offer"]),
    ("refund sent", re.compile(r"\brefund\b.{0,30}\b(sent|on its way|on the way)\b", re.I), ["refund"]),
    ("future assurance", re.compile(r"\b(we'll|we will|we're going to|we are going to)\s+(make sure|ensure|guarantee)\b", re.I), ["ensur", "guarantee"]),
    ("system fix promise", re.compile(r"\b(we're|we are|we'll|we will)\s+(fixing|improving|upgrading|overhauling)\s+(our\s+)?(billing|payment|ordering|booking|delivery|support)\b", re.I), ["fix", "improv", "upgrad", "billing", "system"]),
    ("smooth promise", re.compile(r"\bwill be\s+(smooth|seamless)\b|\bmake sure\b.{0,30}\b(smooth|seamless)\b|\bbilling\b.{0,20}\bsmooth\b", re.I), ["smooth", "seamless"]),
    ("promotion claim", re.compile(r"\bpromotional?\b|\bspecial (pricing|rate|offer)\b|\bfree trial\b|\blimited-time\b", re.I), ["promotion", "promo", "offer", "discount"]),
    ("review-process promise", re.compile(r"\b(we'll|we will|we're going to|let us)\s+(review|audit|assess|evaluate|analyze|check)\b.{0,30}\b(performance|tool|system|logs|data|account)\b", re.I), ["review", "audit"]),
    ("continuous improvement claim", re.compile(r"\b(continually|continuously|constantly|always)\s+(working|striving|improving)\b", re.I), []),
    ("pricing action claim", re.compile(r"\b(reviewing|evaluating|reassessing|revisiting|adjusting|revising)\s+(our\s+)?(pricing|prices|plans|fees)\b", re.I), ["pricing", "review", "plans"]),
    ("committed pricing claim", re.compile(r"\bcommitted to\s+(making|ensuring|keeping|delivering)\b.{0,30}\b(pricing|prices|value|affordable)\b", re.I), []),
    ("value delivery claim", re.compile(r"\b(ensuring?|to ensure)\b.{0,30}\bvalue\b|\breflects?\s+(the\s+)?value\b", re.I), ["value", "pricing"]),
    ("always-looking claim", re.compile(r"\b(always|constantly)\s+(looking|working|striving|aiming)\s+to\b", re.I), []),
    ("pricing rationale claim", re.compile(r"\b(pric\w*|fees?)\s+(reflects?|is based on|are based on|accounts? for|factors? in)\b", re.I), ["pricing", "price"]),
    ("quality standard claim", re.compile(r"\bquality\b.{0,25}\b(we |our )?(provide|deliver|offer|promise|ensure|maintain|stand behind)\b|\bservice standards?\b", re.I), ["quality", "service", "standard"]),
]

# Attitudes and invitations are NOT factual claims — always allowed.
SAFE_HARBOR = [
    "take this seriously", "taken seriously", "looking into",
    "appreciate the opportunity", "opportunity to make",
    "make things right", "make it right",
    "welcome the chance", "hope you'll", "we hope",
    "thank you", "thanks", "sorry", "apologize",
]

CORPORATE_OPENERS = [
    "valuable feedback", "patronage", "exceptional experience",
    "taking the time to provide", "sincerely appreciate your",
    "remain committed", "utmost", "please be advised",
    "it has come to our attention", "do not hesitate",
    "as a valued customer", "your business means",
    "wonderful feedback", "thrilled you enjoyed", "delighted to hear",
    "we're thrilled", "we're delighted", "heartfelt", "cherish",
]

AI_HEAVY_WORDS = [
    "wonderful", "thrilled", "delighted", "elated", "heartfelt",
    "cherish", "cherished", "exquisite", "phenomenal", "outstanding",
    "blessed", "overjoyed", "utmost gratitude", "truly blessed",
]

STRATEGY_IDS = [
    "acknowledge_feedback", "apologize_for_issue", "show_appreciation",
    "address_specific_issue", "reassure_customer", "recommend_related_product",
    "mention_relevant_offer", "encourage_another_visit",
    "invite_private_conversation", "keep_response_minimal",
]

# Strategy id → language that proves execution (with overlap fallback).
STRATEGY_LEXICONS: dict[str, list[str]] = {
    "acknowledge_feedback": ["thank", "feedback", "review", "sharing", "bringing", "telling us"],
    "apologize_for_issue": ["sorry", "apologize", "apology", "apologies", "our apologies"],
    "show_appreciation": ["thank", "appreciate", "glad", "wonderful", "delighted", "thrilled"],
    "address_specific_issue": [],  # covered by issue_coverage, not lexicon
    "reassure_customer": ["take this seriously", "taken seriously", "looking into", "committed",
                          "make things right", "make it right", "appreciate the opportunity"],
    "recommend_related_product": [],  # no verifiable rule; generation instructions govern
    "mention_relevant_offer": [],  # gated by suppression / offer-data skip
    "encourage_another_visit": ["another chance", "chance to", "come back", "visit again",
                                "welcome back", "see you again", "give us another",
                                "make things right", "make it right", "welcome the chance"],
    "invite_private_conversation": ["contact us", "reach out", "privately", "directly", "message us", "get in touch"],
    "keep_response_minimal": [],  # checked via conciseness
}

PROMO_LEXICON = [
    "discount", "coupon", "promo code", "promo", "promotion", "promotional",
    "% off", "percent off", "special offer", "special pricing", "special rate",
    "limited-time", "limited time", "free trial", "use code", "on sale",
]

# Billing-resolution language — forbidden in pricing-only replies
# (price opinion, no transaction error).
BILLING_LANG = [
    re.compile(r"\brefund\b", re.I),
    re.compile(r"\binvoice\b", re.I),
    re.compile(r"\bcharged\b", re.I),
    re.compile(r"\bpayment (failed|error|declined|issue)\b", re.I),
    re.compile(r"\bbilling (issue|error|department|team|inquiry)\b", re.I),
    re.compile(r"\bchargeback\b", re.I),
]

STOPWORDS = frozenset(
    "the a an and or for with was were are our your you that this have has had will would from they them their there here when what which who whom how why not but all any can just don very really much more most than then than".split()
)


def _contains_any(text_lower: str, words: list[str]) -> str | None:
    for w in words:
        if w in text_lower:
            return w
    return None


def _norm_apos(s: str) -> str:
    return (s or "").replace("’", "'").replace("‘", "'")


def _semantic_hit(phrase: str, text_lower: str) -> bool:
    """A multi-word paraphrase matches when all its content cores co-occur.

    "didn't meet your expectations" satisfies "didn't meet expectations" —
    inserted words must not break equivalence.
    """
    text_lower = _norm_apos(text_lower)
    phrase = _norm_apos(phrase.strip().lower())
    if not phrase:
        return False
    if phrase in text_lower:
        return True
    cores = [w for w in re.findall(r"[a-z']{4,}", phrase)]
    return len(cores) >= 2 and all(c in text_lower for c in cores)


def _issue_covered(issue: ExtractedIssue, text_lower: str) -> str | None:
    """An issue is covered by literal keywords OR natural equivalents.

    The reply must never contain the internal key to satisfy this —
    semantic paraphrases (issue.semantic) count the same.
    """
    hit = _contains_any(text_lower, [k.lower() for k in issue.keywords])
    if hit:
        return hit
    for s in (issue.semantic or []):
        if _semantic_hit(s, text_lower):
            return s
    return None


# Internal taxonomy must never leak into customer copy.
TAXONOMY_PATTERN = re.compile(r"\b[a-z]{2,}(?:_[a-z]{2,})+\b")

# Em dash (U+2014) — banned from customer copy, it reads AI-generated.
EM_DASH = "—"


def strip_em_dashes(text: str) -> str:
    """Replace em dashes with commas; collapse leftover spacing.

    Last-resort sanitizer: runs after generation so no reply can reach
    the merchant with an em dash even if the model ignored the ban.
    """
    if not text or EM_DASH not in text:
        return text
    out = re.sub(r"\s*—\s*", ", ", text)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([.,!?;:])", r"\1", out)
    out = re.sub(r",\s*$", "", out)
    return out.strip()
# Spaced classification phrases no real business would write.
TAXONOMY_PHRASES = [
    "product dissatisfaction",
    "service quality",
    "issue type",
    "customer request",
    "product reference",
    "response strategy",
    "strategy fulfillment",
    "validation failed",
]


def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]{5,}", (text or "").lower()) if w not in STOPWORDS]


def _overlap_count(review_text: str, response_lower: str) -> tuple[int, list[str]]:
    """Content-word overlap, tolerant of inflections (wait/waited/waiting)."""
    review_words = set(_content_words(review_text))
    resp_words = set(re.findall(r"[a-z]{4,}", response_lower or ""))
    matched: set[str] = set()
    for rw in review_words:
        if rw in response_lower:
            matched.add(rw)
            continue
        stem = rw[:5]
        if any(sw.startswith(stem) or stem.startswith(sw[:5]) for sw in resp_words):
            matched.add(rw)
    return len(matched), sorted(matched)


def validate_response(
    response: GeneratedResponse,
    analysis: ReviewAnalysis,
    channel_policy: dict,
    review_text: str = "",
    issues: list[ExtractedIssue] | None = None,
    active_strategies: list | None = None,
    suppressed_ids: list[str] | None = None,
    tier: dict | None = None,
    business_context: str | None = None,
    has_offer_data: bool = False,
    rating: int | None = None,
    promo_max_ctas: int | None = None,
) -> ValidationResult:
    """Policy + fulfillment + grounding + quality. New args optional (legacy tests)."""
    checks: dict[str, bool] = {}
    problems: list[str] = []
    fulfillment: list[StrategyFulfillment] = []
    text = response.response_text or ""
    text_lower = text.lower()
    issues = issues or []
    active_strategies = active_strategies or []
    suppressed_ids = suppressed_ids or []
    tier = tier or select_tier(rating, analysis, review_text)
    context_lower = (business_context or "").lower()

    # ── Policy checks ─────────────────────────────────────
    privacy_ok = True
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(text):
            privacy_ok = False
            problems.append(f"Potential PII detected: {pattern.pattern[:50]}")
    checks["privacy"] = privacy_ok

    hallucination_ok = True
    for pattern in HALLUCINATION_PATTERNS:
        if pattern.search(text):
            hallucination_ok = False
            problems.append(f"Potential hallucinated action: {pattern.pattern[:50]}")
    checks["hallucination"] = hallucination_ok

    instruction_ok = True
    for pattern in INSTRUCTION_IGNORE_PATTERNS:
        if pattern.search(text):
            instruction_ok = False
            problems.append("Policy violation: asking to change review or promising fix")
    checks["instruction_compliance"] = instruction_ok

    # Promotional CTA cap — only enforced when the merchant opted into
    # promotion (caller passes the configured max); otherwise untouched.
    promo_ok = True
    if promo_max_ctas is not None:
        cta_count = len(re.findall(r"https?://\S+", text))
        if cta_count > promo_max_ctas:
            promo_ok = False
            problems.append(
                f"Too many promotional links: {cta_count} found, "
                f"at most {promo_max_ctas} allowed — keep only the most relevant one."
            )
    checks["promo_cta"] = promo_ok

    max_len = channel_policy.get("max_length", 500)
    length_ok = len(text) <= max_len
    checks["length"] = length_ok
    if not length_ok:
        problems.append(f"Response too long: {len(text)} > {max_len} chars")

    sensitive_info_ok = True
    if channel_policy.get("public", False) and not channel_policy.get("allow_sensitive_information", True):
        for pattern in SENSITIVE_PATTERNS[:2]:
            if pattern.search(text):
                sensitive_info_ok = False
                problems.append("Sensitive info in public channel")
    checks["sensitive_info"] = sensitive_info_ok

    non_empty = bool(text.strip())
    checks["non_empty"] = non_empty

    sentiment_ok = True
    if analysis.sentiment in ("very_negative", "negative"):
        dismissive_words = ["whatever", "not our problem", "that's fine", "noted"]
        if any(w in text_lower for w in dismissive_words):
            sentiment_ok = False
            problems.append("Response may be dismissive for a negative review")
    checks["sentiment_appropriate"] = sentiment_ok

    # ── Completeness ──────────────────────────────────────
    complete_ok = True
    stripped = text.strip()
    if stripped.startswith("{") or '"response_text"' in stripped[:40]:
        complete_ok = False
        problems.append("Incomplete response: raw JSON leaked into the reply text.")
    elif len(stripped) < 40:
        complete_ok = False
        problems.append(f"Incomplete response: too short to be complete ({len(stripped)} chars).")
    elif stripped[-1] not in ".!?…":
        complete_ok = False
        problems.append("Incomplete response: ends mid-sentence — likely truncated.")
    checks["response_completeness"] = complete_ok

    # ── Issue coverage ────────────────────────────────────
    # Concrete (pattern-extracted) facts must ALL appear — via literal
    # keywords OR natural equivalents (never the internal key).
    # Generic (inferred) issues guide but never block alone.
    coverage_ok = True
    missing_issues: list[str] = []
    concrete_issues = [i for i in issues if not i.generic]
    for issue in concrete_issues:
        if not _issue_covered(issue, text_lower):
            coverage_ok = False
            missing_issues.append(f"{issue.label} ({issue.detail})")
    if not concrete_issues and issues:
        if not any(_issue_covered(i, text_lower) for i in issues):
            coverage_ok = False
            missing_issues.append("complaint subject (" + ", ".join(i.detail for i in issues) + ")")
    checks["issue_coverage"] = coverage_ok
    if not coverage_ok:
        problems.append(f"Unaddressed complaint facts: {', '.join(missing_issues)}")

    # ── Specificity ───────────────────────────────────────
    n_overlap, matched_words = _overlap_count(review_text, text_lower)
    # Product reference (even short like "AI") counts as specificity when echoed
    product_ref = (getattr(analysis, "product_reference", None) or "").strip()
    product_echoed = bool(product_ref and product_ref.lower() in text_lower)
    # Short positive praise with nothing concrete has no specificity burden
    is_short_praise = (
        not issues
        and getattr(analysis, "sentiment", "") in ("positive", "very_positive")
        and len((review_text or "").strip()) < 80
    )
    # Non-English replies can't be word-overlap checked (lexicons are English
    # and content words are [a-z]-based) — specificity falls back to issue
    # coverage (Arabic keywords still match) and length guards.
    non_english = bool(
        getattr(analysis, "language", None)
        and (analysis.language or "en").strip().lower() != "en"
    )
    if len(review_text or "") >= 30:
        specific_ok = (
            n_overlap >= 3 or (bool(issues) and coverage_ok)
            or product_echoed or is_short_praise or non_english
        )
    else:
        specific_ok = n_overlap >= 1 or len(stripped) < 120 or product_echoed or is_short_praise or non_english
    checks["specificity"] = specific_ok
    if not specific_ok:
        problems.append(f"Generic reply: only {n_overlap} concrete review word(s) echoed.")

    # ── Claim grounding: patterns + extracted-claim verdicts ──
    grounding_ok = True
    for name, pattern, stems in OPERATIONAL_CLAIMS:
        m = pattern.search(text)
        if not m:
            continue
        grounded = bool(stems) and any(s in context_lower for s in stems)
        if not grounded:
            grounding_ok = False
            problems.append(
                f"Unsupported business claim ('{m.group(0).strip()}', type: {name}) — "
                f"remove it or ground it in databank data."
            )
    # Link grounding: every URL must appear verbatim in Business Context.
    link_ok = True
    for url in re.findall(r"https?://\S+", text):
        cleaned = url.rstrip(".,)]}>\"'")
        if cleaned.lower() not in context_lower:
            link_ok = False
            grounding_ok = False
            problems.append(f"Invented link ('{cleaned[:80]}') — no matching URL in databank context.")
    checks["link_grounding"] = link_ok

    # Engine-level: every factual claim must trace to retrieved context.
    claim_verdicts: list[ClaimVerdict] = []
    for v in ground_claims(extract_claims(text), business_context):
        claim_verdicts.append(ClaimVerdict(**v))
        if v["status"] == "UNSUPPORTED":
            grounding_ok = False
            problems.append(
                f"Unsupported business claim ('{v['claim'][:90]}', type: {v['kind']}) — "
                f"no evidence in databank context."
            )
    # A never-again promise has no valid grounding — always fails (caught above).
    checks["claim_grounding"] = grounding_ok
    # Fold into hallucination so the old badge stays meaningful.
    checks["hallucination"] = hallucination_ok and grounding_ok

    # ── Offer appropriateness ─────────────────────────────
    offer_ok = True
    if "mention_relevant_offer" in suppressed_ids:
        hit = _contains_any(text_lower, PROMO_LEXICON)
        if hit:
            offer_ok = False
            problems.append(f"Suppressed promotional content present ('{hit}') for a churning customer.")
    checks["offer_appropriateness"] = offer_ok

    # ── Pricing purity: price opinions must not get billing language ──
    has_pricing = any(i.key == "pricing" for i in issues)
    has_billing = any(i.key == "billing" for i in issues) or (analysis.issue_type or "") == "billing"
    pricing_ok = True
    if has_pricing and not has_billing:
        for pattern in BILLING_LANG:
            m = pattern.search(text)
            if m:
                pricing_ok = False
                problems.append(
                    f"Billing-resolution language in a pricing reply ('{m.group(0).strip()}') — "
                    f"this is a price concern, not a billing error."
                )
                break
    checks["pricing_purity"] = pricing_ok

    # ── Per-strategy fulfillment (semantic, not just keywords)
    # Required tiers block approval; best-effort failures are warnings —
    # the reply must never be padded just to satisfy a LOW strategy.
    from .strategies import BEST_EFFORT

    for s in active_strategies:
        sid = s.strategy_id
        name = getattr(s, "name", sid)
        status, reason, evidence = _check_strategy(
            sid, text_lower, text, issues, review_text, n_overlap, has_offer_data,
            analysis, non_english=non_english)
        fulfillment.append(StrategyFulfillment(
            strategy_id=sid, strategy=name,
            status=status, reason=reason, evidence=evidence,
        ))
        if status == "fail":
            if sid in BEST_EFFORT:
                problems.append(f"Best-effort strategy '{name}' not visibly executed: {reason}")
            else:
                problems.append(f"Strategy '{name}' unfulfilled: {reason}")

    fulfillment_ok = all(
        f.status == "pass" or f.strategy_id in BEST_EFFORT for f in fulfillment
    )
    checks["strategy_fulfillment"] = fulfillment_ok

    # ── Final quality pass ────────────────────────────────
    words = count_words(text)
    sentences = count_sentences(text)
    concise_ok = words <= int(tier["max_words"] * 1.3) and sentences <= tier["max_sentences"] + 1
    checks["conciseness"] = concise_ok
    if not concise_ok:
        problems.append(
            f"Too long for a {tier['label']} reply: {words} words / {sentences} sentences "
            f"(target ≤{tier['max_words']} words, ≤{tier['max_sentences']} sentences). Compress strategies into fewer sentences."
        )

    natural_ok, natural_reason = _check_naturalness(text, text_lower)
    checks["naturalness"] = natural_ok
    if not natural_ok:
        problems.append(natural_reason)

    # ── Taxonomy leak: internal labels must never reach the customer ──
    leak = TAXONOMY_PATTERN.search(text_lower)
    leak_phrase = next((p for p in TAXONOMY_PHRASES if p in text_lower), None)
    checks["taxonomy_leak"] = leak is None and leak_phrase is None
    if leak:
        problems.append(
            f"Internal taxonomy leaked into reply ('{leak.group(0)}') — "
            f"rephrase in natural customer-facing words."
        )
    if leak_phrase:
        problems.append(
            f"Classification phrasing leaked into reply ('{leak_phrase}') — "
            f"rephrase in natural customer-facing words."
        )

    # ── "Does this actually help?" summary badge ──────────
    # (Specific failures are already reported above; this is the roll-up.)
    helpful_keys = ["issue_coverage", "claim_grounding", "link_grounding", "hallucination",
                    "offer_appropriateness", "naturalness", "conciseness",
                    "taxonomy_leak", "pricing_purity"]
    checks["helpfulness"] = all(checks.get(k, True) for k in helpful_keys)

    passed = all(checks.values())
    return ValidationResult(
        passed=passed, checks=checks, issues=problems,
        strategy_fulfillment=fulfillment, claim_verdicts=claim_verdicts,
    )


def _check_strategy(
    sid: str,
    text_lower: str,
    text: str,
    issues: list[ExtractedIssue],
    review_text: str,
    n_overlap: int,
    has_offer_data: bool,
    analysis=None,
    non_english: bool = False,
) -> tuple[str, str, str]:
    """Return (status, reason, evidence) for one strategy."""
    if sid == "address_specific_issue":
        if not issues:
            return "pass", "No concrete issues extracted; nothing to cover.", ""
        concrete = [i for i in issues if not i.generic]
        missing = [i for i in concrete if not _issue_covered(i, text_lower)]
        if missing:
            return ("fail",
                    f"Missing concrete complaint details: {', '.join(i.detail for i in missing)}.",
                    "")
        # Generic (inferred) issues guide generation but never block alone:
        # at least one extracted fact must surface when nothing concrete exists.
        if not concrete:
            any_hit = [
                (_issue_covered(i, text_lower) or "") for i in issues
            ]
            any_hit = [h for h in any_hit if h][:4]
            if not any_hit:
                return ("fail", "No complaint fact referenced at all — address what the customer said.", "")
            return "pass", "Referenced complaint subject.", f"matched: {', '.join(any_hit)}"
        hits = [(_issue_covered(i, text_lower) or "") for i in issues]
        hits = [h for h in hits if h][:4]
        return "pass", "All extracted facts referenced.", f"matched: {', '.join(hits)}"

    if sid == "mention_relevant_offer":
        if not has_offer_data:
            return "pass", "Correctly omitted — no verified offer in databank context.", ""
        hit = _contains_any(text_lower, PROMO_LEXICON + ["offer", "deal", "complimentary"])
        if hit:
            return "pass", "Offer language present.", f"matched: '{hit}'"
        return ("fail", "Strategy requires mentioning a real offer, but none appears.", "")

    if sid in ("recommend_related_product",):
        return "pass", "No verifiable product rule; generation instructions govern this.", ""

    if sid == "keep_response_minimal":
        if len(text) <= 300:
            return "pass", f"Reply is concise ({len(text)} chars).", ""
        return "fail", f"Reply exceeds minimal style ({len(text)} chars).", ""

    lexicon = STRATEGY_LEXICONS.get(sid)
    if not lexicon:
        return "pass", "No fulfillment rule defined.", ""
    hit = _contains_any(text_lower, lexicon)
    if hit:
        # Anti-gaming: a stock phrase alone proves nothing — except for
        # short positive praise with nothing concrete to engage (star-only,
        # "greatttt", "love it"). There, a warm thank-you *is* the engagement.
        is_short_praise = (
            not issues
            and (analysis.sentiment in ("positive", "very_positive") if hasattr(analysis, "sentiment") else False)
            and len((review_text or "").strip()) < 80
        )
        any_covered = any(_issue_covered(i, text_lower) for i in issues)
        engaged = n_overlap >= 1 or any_covered or len((review_text or "").strip()) < 30 or is_short_praise
        if not engaged:
            return ("fail",
                    f"Stock phrase ('{hit}') without engaging the review subject — "
                    f"reference what the customer actually said.", "")
        return "pass", f"Required language present ('{hit}') with subject engagement.", _evidence_sentence(text, hit)
    # Semantic fallback: subject-matter engagement proves the strategy
    # even without stock phrases (acknowledge / appreciate / reassure).
    # Short issue keywords (cold, 45, rude) don't count as content words,
    # so genuine coverage compensates: covered facts = engaged.
    if sid in ("acknowledge_feedback", "show_appreciation", "reassure_customer"):
        covered = bool(issues) and all(
            _issue_covered(i, text_lower) for i in issues
        )
        if n_overlap >= 4 or covered or (not issues and n_overlap >= 2):
            return ("pass",
                    f"No stock phrase, but subject engaged ({n_overlap} review words referenced).", "")
    # Non-English replies: the English lexicon can't match by design — judge
    # engagement instead (Arabic issue keywords still match; praise needs
    # nothing concrete). Never force an Arabic reply into English phrasing.
    if non_english:
        any_covered = any(_issue_covered(i, text_lower) for i in issues)
        covered = bool(issues) and all(
            _issue_covered(i, text_lower) for i in issues
        )
        short_praise = (
            not issues
            and getattr(analysis, "sentiment", "") in ("positive", "very_positive")
            and len((review_text or "").strip()) < 80
        )
        if any_covered or covered or short_praise or not issues:
            return ("pass",
                    "Non-English reply — English lexicon not applicable; subject engagement verified.", "")
    return ("fail", f"Missing required language (expected one of: {', '.join(lexicon[:4])}).", "")


def _evidence_sentence(text: str, hit: str) -> str:
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if hit in sent.lower():
            return sent.strip()[:160]
    return ""


def _check_naturalness(text: str, text_lower: str) -> tuple[bool, str]:
    """Reject corporate-voice, repetitive, or strategy-leaking replies."""
    if EM_DASH in (text or ""):
        return False, "Em dash detected ('—') — rewrite using commas or periods instead."
    for opener in CORPORATE_OPENERS:
        if opener in text_lower:
            return False, f"Corporate phrasing detected ('{opener}') — rewrite like a real person."
    for w in AI_HEAVY_WORDS:
        if w in text_lower:
            return False, f"AI-heavy word detected ('{w}') — use simple human words like thanks/glad/sorry instead."
    for sid in STRATEGY_IDS:
        if sid in text_lower:
            return False, f"Strategy name leaked into reply ('{sid}')."
    if "as an ai" in text_lower or "language model" in text_lower:
        return False, "AI self-reference leaked into reply."
    sentences = [s.strip().lower() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) != len(set(sentences)) and len(sentences) > 1:
        return False, "Repeated sentence detected — compress."
    words = re.findall(r"[a-z']+", text_lower)
    seen5: set[str] = set()
    for i in range(len(words) - 4):
        gram = " ".join(words[i:i + 5])
        if gram in seen5:
            return False, f"Repeated phrasing detected ('{gram}...') — compress."
        seen5.add(gram)
    return True, ""
