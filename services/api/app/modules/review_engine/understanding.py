"""Analyze a review into a structured representation via a single LLM call."""
import json
import logging
import time

from ..llm.providers.base import LLMMessage, LLMRequest, ProviderError
from ..llm.providers.registry import get_provider_for_model
from ..llm.service import _resolve_model
from .schemas import ReviewAnalysis

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """You are a review analysis engine. Analyze the customer review and return a JSON object with these fields:

- sentiment: one of "very_negative", "negative", "neutral", "positive", "very_positive"
- emotion: a single word describing the customer's emotion (e.g. "anger", "frustration", "joy", "disappointment", "indifference")
- intent: array of strings from ["complaint", "praise", "suggestion", "refund_request", "question", "recommendation_request"]
- issue_type: string or null — see the pricing-vs-billing rules below
- product_reference: string or null — the specific product/service mentioned
- urgency: one of "low", "medium", "high", "critical"
- customer_request: string or null — what the customer is explicitly asking for
- language: ISO 639-1 code (e.g. "en", "ar")

ISSUE TYPE RULES — classify by what the customer is ACTUALLY complaining about:

Use "pricing" when the complaint is that the price is too high (an opinion
about value). Signals: expensive, costly, too expensive, overpriced, pricey,
price is high, not worth the price/money. There is NO transaction error.
Example: "The AI tool is great but too expensive." → issue_type "pricing".

Use "billing" ONLY when something went wrong with a transaction. Signals:
charged twice, double charge, wrong amount charged, unexpected charge,
payment failed/declined, invoice is wrong, billing error, charged for
something not ordered. Example: "I was charged twice." → "billing".

CRITICAL: the mere presence of "cost", "price", "charge", or "refund" does
NOT make it billing. "Costly" alone is pricing. "I want a refund" with no
charge error is a refund_request intent, not a billing issue_type.
When in doubt between pricing opinion and billing error, prefer "pricing"
unless a specific transaction failure is described.

Other issue types: "product_quality", "product_dissatisfaction",
"service_quality", "delivery", "wait_time", "cleanliness", "staff_behavior",
"technical_issue", "general_complaint", or null.

Return ONLY valid JSON. No explanation. No markdown."""


def _salvage_analysis_json(raw: str) -> dict:
    """Extract whatever fields survived a truncated/invalid JSON blob.

    Models sometimes stop mid-object (token cut) — 6 good fields should not
    be trashed because the 7th got cut. Missing fields fall to ReviewAnalysis
    defaults via .get() at the call site.
    """
    import re

    data: dict = {}

    def _str_field(name: str) -> str | None:
        m = re.search(rf'"{name}"\s*:\s*"([^"]*)"', raw)
        return m.group(1) if m else None

    for field in ("sentiment", "emotion", "issue_type", "product_reference",
                  "urgency", "customer_request", "language"):
        val = _str_field(field)
        # JSON null literal (unquoted) → treat as absent
        if val is None and re.search(rf'"{field}"\s*:\s*null', raw):
            continue
        if val is not None:
            data[field] = val

    m = re.search(r'"intent"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
    if m:
        data["intent"] = re.findall(r'"([^"]+)"', m.group(1))

    return data


async def analyze_review(
    review_text: str,
    rating: int,
    reviewer_name: str | None,
    model: str,
    tenant_id: str | None = None,
    channel_id: str | None = None,
) -> tuple[ReviewAnalysis, dict]:
    """Analyze a review and return structured analysis + usage stats."""
    user_msg = (
        f"Rating: {rating}/5 stars\n"
        f"Reviewer: {reviewer_name or 'anonymous'}\n"
        f"Review:\n\"{review_text.strip()[:2000]}\""
    )

    provider = get_provider_for_model(model)
    api_model, _ = _resolve_model(model)

    t0 = time.monotonic()
    try:
        resp = await provider.complete(
            LLMRequest(
                model=api_model,
                messages=[LLMMessage(role="user", content=user_msg)],
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=500,
                stream=False,
                tenant_id=tenant_id,
                model_id=model,
                purpose="review_engine.analysis",
                channel_id=channel_id,
            )
        )
    except ProviderError:
        logger.warning("Analysis model %s failed; no fallback — surfacing error", model)
        raise

    latency = int((time.monotonic() - t0) * 1000)
    raw = resp.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Strict analysis parse failed, salvaging fields: %s", raw[:200])
        data = _salvage_analysis_json(raw)

    # Sanitize enums (salvaged or model-invented values must not fail validation)
    if data.get("sentiment") not in ("very_negative", "negative", "neutral", "positive", "very_positive"):
        data["sentiment"] = "neutral"
    if data.get("urgency") not in ("low", "medium", "high", "critical"):
        data["urgency"] = "low"
    if not isinstance(data.get("intent"), list):
        data["intent"] = []
    if not data.get("emotion"):
        data["emotion"] = "unknown"

    analysis = ReviewAnalysis(
        sentiment=data.get("sentiment", "neutral"),
        emotion=data.get("emotion", "unknown"),
        intent=data.get("intent", []),
        issue_type=data.get("issue_type"),
        product_reference=data.get("product_reference"),
        urgency=data.get("urgency", "low"),
        customer_request=data.get("customer_request"),
        language=data.get("language", "en"),
    )
    usage = {
        "model": model,
        "tokens": resp.usage.total_tokens,
        "latency_ms": latency,
    }
    return analysis, usage


def _rule_based_analysis(review_text: str, rating: int) -> ReviewAnalysis:
    """Fallback when LLM fails — basic sentiment from rating."""
    if rating >= 4:
        sentiment = "positive" if rating == 4 else "very_positive"
    elif rating == 3:
        sentiment = "neutral"
    else:
        sentiment = "negative" if rating == 4 else "very_negative"

    text = review_text.lower() if review_text else ""
    issue_type = None
    product_ref = None

    issue_keywords = {
        "product_quality": ["quality", "broken", "defective", "terrible", "bad"],
        "delivery": ["delivery", "late", "slow", "shipping", "arrived"],
        "service_quality": ["service", "rude", "unhelpful", "staff", "wait"],
        "cleanliness": ["dirty", "clean", "hygiene", "filthy"],
        # Transaction errors only — price opinions are "pricing", not billing.
        "billing": ["charged twice", "double charge", "unexpected charge", "payment failed", "invoice"],
        "pricing": ["expensive", "costly", "overpriced", "pricey", "too expensive", "not worth"],
    }
    for itype, keywords in issue_keywords.items():
        if any(kw in text for kw in keywords):
            issue_type = itype
            break

    if rating <= 2:
        urgency = "medium"
    elif rating == 3:
        urgency = "low"
    else:
        urgency = "low"

    intent = []
    if rating <= 2:
        intent.append("complaint")
    if rating >= 4:
        intent.append("praise")
    if any(w in text for w in ["refund", "money back", "return"]):
        intent.append("refund_request")

    return ReviewAnalysis(
        sentiment=sentiment,
        emotion="frustration" if rating <= 2 else "satisfaction" if rating >= 4 else "indifference",
        intent=intent,
        issue_type=issue_type,
        product_reference=product_ref,
        urgency=urgency,
        customer_request=review_text[:200] if review_text else None,
        language="en",
    )
