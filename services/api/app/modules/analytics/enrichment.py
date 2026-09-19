"""Per-review AI enrichment: sentiment, topics, products, problems.

Runs inside the analytics Kafka consumer. Uses the tenant's LLM catalog
(strict-JSON prompt) with a deterministic keyword/rating heuristic fallback,
so the pipeline never stalls when the LLM is unavailable — matching the
graceful-degradation pattern used across the codebase (Kafka, Redis).
"""
import json
import logging
import re

from ..llm.providers.base import LLMMessage, LLMRequest, ProviderError
from ..llm.providers.registry import get_provider_for_model

logger = logging.getLogger(__name__)

ENRICHMENT_MODEL = "groq:oss-120b"

SYSTEM_PROMPT = """You are a review analytics engine. Analyse the customer review and
respond with STRICT JSON only (no markdown fences, no commentary).

Schema:
{
  "sentiment": "positive" | "neutral" | "negative",
  "sentiment_score": <float -1.0..1.0>,
  "topics": [{"name": "<service|staff|price|quality|waiting time|cleanliness|location|delivery|atmosphere|communication|other>", "sentiment": "positive|neutral|negative"}],
  "products": [{"name": "<product or service mentioned>", "sentiment": "positive|neutral|negative"}],
  "problems": [{"name": "<specific problem, lowercase>", "severity": "low|medium|high"}]
}

Rules:
- topics: only topics actually discussed. Use the listed canonical names.
- products: only concrete named products/services; empty list if none.
- problems: only genuine complaints; empty list if none.
- sentiment_score: -1.0 (angry) to 1.0 (delighted)."""


_TOPIC_RULES = {
    "service": ["service", "staff", "waiter", "waitress", "cashier", "team", "employee", "manager", "helpful", "rude"],
    "waiting time": ["wait", "waiting", "slow", "queue", "delay", "forever", "took ages", "line"],
    "price": ["price", "expensive", "cheap", "cost", "overpriced", "value", "affordable", "charge"],
    "quality": ["quality", "fresh", "taste", "delicious", "cold", "stale", "burnt", "portion", "flavor", "flavour"],
    "cleanliness": ["clean", "dirty", "hygiene", "messy", "spotless", "filthy", "tidy"],
    "location": ["location", "parking", "access", "find", "address", "crowded"],
    "delivery": ["delivery", "delivered", "driver", "shipping", "package", "arrived", "courier"],
    "atmosphere": ["atmosphere", "ambience", "music", "noisy", "cozy", "vibe", "decor"],
    "communication": ["called", "phone", "response", "email", "answered", "contact", "communication", "reply"],
}


def _heuristic_enrich(rating: int, text: str | None) -> dict:
    """Deterministic fallback: rating-driven sentiment + keyword topic match."""
    if rating >= 4:
        sentiment, score = "positive", 0.6 if rating == 4 else 0.9
    elif rating == 3:
        sentiment, score = "neutral", 0.0
    else:
        sentiment, score = "negative", -0.6 if rating == 2 else -0.9

    lower = (text or "").lower()
    topics: list[dict] = []
    for topic, keywords in _TOPIC_RULES.items():
        if any(k in lower for k in keywords):
            topics.append({"name": topic, "sentiment": sentiment})
    return {
        "sentiment": sentiment,
        "sentiment_score": score,
        "topics": topics,
        "products": [],
        "problems": [{"name": t["name"], "severity": "high" if rating <= 2 else "medium"} for t in topics if sentiment == "negative"],
    }


def _extract_json(raw: str) -> dict | None:
    """Best-effort JSON extraction from an LLM response."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _valid_result(data: dict) -> dict:
    """Normalise + validate LLM output into the stored shape."""

    def _clamp(v, lo, hi, default):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return default

    sentiment = str(data.get("sentiment", "neutral")).lower()
    if sentiment not in ("positive", "neutral", "negative"):
        sentiment = "neutral"

    def _clean_list(items, sent_key="sentiment"):
        out = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            entry = {"name": str(item["name"])[:100].lower() if sent_key == "severity" else str(item["name"])[:100]}
            sev = str(item.get(sent_key, "neutral")).lower()
            entry[sent_key] = sev if sev in ("positive", "neutral", "negative", "low", "medium", "high") else ("medium" if sent_key == "severity" else "neutral")
            out.append(entry)
        return out[:20]

    return {
        "sentiment": sentiment,
        "sentiment_score": _clamp(data.get("sentiment_score"), -1.0, 1.0, 0.0),
        "topics": _clean_list(data.get("topics")),
        "products": _clean_list(data.get("products")),
        "problems": _clean_list(data.get("problems"), sent_key="severity"),
    }


async def enrich_review(
    rating: int,
    text: str | None,
    reviewer_name: str | None,
    model: str = ENRICHMENT_MODEL,
    tenant_id: str | None = None,
) -> dict:
    """Return {sentiment, sentiment_score, topics, products, problems} for a review."""
    if not text or not text.strip():
        # Star rating alone: sentiment from stars, nothing else to mine.
        return _heuristic_enrich(rating, None)

    try:
        provider = get_provider_for_model(model)
        from ..llm.service import _resolve_model

        api_model, _ = _resolve_model(model)
        description = text.strip()[:2000]
        user_msg = (
            f"Review by {reviewer_name or 'an anonymous customer'} — {rating}/5 stars:\n"
            f"\"{description}\""
        )
        resp = await provider.complete(
            LLMRequest(
                model=api_model,
                messages=[LLMMessage(role="user", content=user_msg)],
                system_prompt=SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=600,
                stream=False,
                tenant_id=tenant_id,
                model_id=model,
                purpose="analytics.enrichment",
            )
        )
        data = _extract_json(resp.content)
        if data is None:
            raise ProviderError(model, "Enrichment response was not valid JSON", 502)
        return _valid_result(data)
    except Exception as e:
        logger.warning("LLM enrichment failed (%s); using heuristic fallback: %s", model, e)
        return _heuristic_enrich(rating, text)
