"""Per-review AI enrichment: sentiment, topics, products, problems, meaning.

Runs inside the analytics Kafka consumer. Uses the tenant's LLM catalog
(strict-JSON prompt) with a deterministic keyword/rating heuristic fallback,
so the pipeline never stalls when the LLM is unavailable — matching the
graceful-degradation pattern used across the codebase (Kafka, Redis).

The `meaning` half is the part that matters for trust. A language model asked
to summarise a set of reviews will invent a plausible complaint nobody made: it
read the Arabic "you need to fix your building" as "bank account corrections"
and then propagated that through a theme, an opportunity and a business
action. Telling it not to do that in the prompt did not help.

So meaning is extracted per review and then *checked in code* (see subjects.py):
the subject must come from a closed vocabulary, and every evidence span must
appear verbatim in the review. A complaint that cannot be grounded is marked
`needs_human` and surfaced, never believed and never forced into a theme.
"""
import json
import logging
import re

from ..llm.providers.base import LLMMessage, LLMRequest, ProviderError
from ..llm.providers.registry import get_provider_for_model

logger = logging.getLogger(__name__)

ENRICHMENT_MODEL = "groq:qwen3.8-27b"
MEANING_VERSION = 2

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


# ── Meaning layer ────────────────────────────────────────────────

MEANING_SYSTEM_PROMPT = """You extract what a single customer review MEANS.

Return STRICT JSON only (no markdown fences, no commentary):

{
  "intent": "<what the customer is doing: praising, complaining, asking, warning>",
  "subject": "<ONE value from the list below>",
  "problem": "<the complaint in the customer's own framing, or null>",
  "asks": ["<what the customer is asking for, verbatim where possible>"],
  "entities": {"product": [], "location": [], "staff": [], "dates": []},
  "negated": <true if the review DENIES something it would otherwise imply, e.g. no problems>,
  "sentiment": "positive" | "neutral" | "negative",
  "intensity": <float 0.0..1.0, strength of feeling>,
  "evidence": ["<short spans copied VERBATIM from the review that support the above>"],
  "confidence": <float 0.0..1.0>
}

SUBJECT must be exactly one of:
{subjects}

Rules:
- Judge the REVIEW, never the reviewer.
- Classify the customer's actual subject, not what seems plausible for the
    business. Any tenant can receive reviews about its office/building; never
    infer the review topic from tenant or business context.
- Distinguish carefully: facility_premises = a physical place/building,
    repairs, maintenance, cleanliness or facilities; billing_payments = a charge,
    invoice, payment or refund; account_access = login, credentials or digital
    account access. These are not interchangeable. A building mention is not a
    bank/account issue unless the review explicitly says so.
- Being negative is NOT a problem by itself. Only assign a subject when the
    review actually raises that issue; otherwise use "other" and lower confidence.
- If nothing fits, use "other" and set confidence low. DO NOT invent an issue.
- evidence MUST be copied character-for-character from the review. Never
  translate, paraphrase, or invent a quote. 2-8 words is ideal.
- If the review is in a language other than English, still copy evidence in
  that language. Do not translate the evidence.
- "negated" is true when the customer denies something, e.g. "no problems",
  "nothing to complain about", "not fresh". Read it carefully; the difference
  is a few characters.

Return an empty object if the review has no text at all."""


def _meaning_prompt() -> str:
    from .subjects import SUBJECTS

    allowed = "\n".join(f"- {key}: {label}" for key, label in SUBJECTS.items())
    return MEANING_SYSTEM_PROMPT.replace("{subjects}", allowed)


def _blank_meaning(*, reason: str, language: str, source: str) -> dict:
    """A meaning record that asserts nothing.

    Used whenever we cannot ground an interpretation. `needs_human` is the
    point: an ungrounded review must be visible to a person, not silently
    filed under a theme the model made up.
    """
    return {
        "intent": None,
        "subject": "other",
        "problem": None,
        "asks": [],
        "entities": {"product": [], "location": [], "staff": [], "dates": []},
        "negated": False,
        "intensity": 0.0,
        "evidence": [],
        "confidence": 0.0,
        "needs_human": True,
        "source": source,
        "reason": reason,
        "language": language,
        "corrected_at": None,
        "version": MEANING_VERSION,
    }


async def extract_meaning(
    *,
    text: str | None,
    rating: int,
    reviewer_name: str | None = None,
    model: str = ENRICHMENT_MODEL,
    tenant_id: str | None = None,
) -> dict:
    """Work out what one review means, and refuse to guess.

    Always returns a record. When the model cannot be reached, returns junk, or
    returns something whose evidence is not in the review, the record is
    `needs_human` with `confidence` 0 — so the failure shows up in the UI as
    work for a person rather than as a fabricated finding.
    """
    from . import subjects as S

    body = (text or "").strip()
    language = S.detect_language(body)
    if not body:
        return _blank_meaning(reason="no review text", language=language, source="llm")

    try:
        from ..llm.providers.base import LLMMessage, LLMRequest
        from ..llm.providers.registry import get_provider_for_model
        from ..llm.service import _resolve_model

        provider = get_provider_for_model(model)
        api_model, _ = _resolve_model(model)
        resp = await provider.complete(
            LLMRequest(
                model=api_model,
                messages=[LLMMessage(role="user", content=json.dumps({
                    "rating": rating,
                    "reviewer_name": reviewer_name or "an anonymous customer",
                    "review_text": body[:2000],
                }))],
                system_prompt=_meaning_prompt(),
                temperature=0.0,
                max_tokens=500,
                stream=False,
                tenant_id=tenant_id,
                model_id=model,
                purpose="analytics.meaning",
            )
        )
        data = _extract_json(resp.content)
    except Exception as e:
        logger.warning("meaning extraction unavailable (%s): %s", model, e)
        return _blank_meaning(reason="llm unavailable", language=language, source="llm")

    if not isinstance(data, dict) or not data:
        return _blank_meaning(reason="unparseable output", language=language, source="llm")

    subject = S.coerce_subject(data.get("subject"))
    if subject is None:
        # The model invented a category. That is the exact failure this layer
        # exists to stop, so it is recorded rather than coerced into a legal one.
        return _blank_meaning(
            reason=f"invented subject: {str(data.get('subject'))[:60]!r}",
            language=language,
            source="llm",
        )

    if S.subject_conflicts_with_text(subject, body):
        return _blank_meaning(
            reason="subject conflicts with review evidence",
            language=language,
            source="llm",
        )

    evidence = S.filter_evidence(
        data.get("evidence") if isinstance(data.get("evidence"), list) else None,
        body,
    )
    confidence = S.coerce_confidence(data.get("confidence"))

    # A complaint with nothing supporting it in the review is a fabrication.
    # A praise-only review legitimately has no evidence spans, so only gate the
    # negative case — that is the one that produces business actions.
    is_negative = str(data.get("sentiment", "")).lower() in ("negative", "neutral")
    if is_negative and not evidence:
        return _blank_meaning(
            reason="no verbatim evidence for the complaint",
            language=language,
            source="llm",
        )

    # Cross-check the model's negation answer against the text. Where they
    # disagree, drop confidence rather than trusting either: "no problems" and
    # "there is a problem" differ by a few characters in both languages.
    model_negated = bool(data.get("negated"))
    text_negated = S.has_negation(body)
    if model_negated != text_negated:
        confidence = round(confidence * 0.6, 3)

    needs_human = confidence < S.AUTO_ACCEPT_CONFIDENCE
    record = {
        "intent": _clean_str(data.get("intent"), 60),
        "subject": subject,
        "problem": _clean_str(data.get("problem"), 300),
        "asks": _clean_list(data.get("asks"), 5, 120),
        "entities": _clean_entities(data.get("entities")),
        "negated": model_negated,
        "intensity": S.coerce_confidence(data.get("intensity")),
        "evidence": evidence,
        "confidence": confidence,
        "needs_human": needs_human,
        "source": "llm",
        "reason": "low confidence" if needs_human else None,
        "language": language,
        "corrected_at": None,
        "version": MEANING_VERSION,
    }
    return record


def _clean_str(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    return trimmed[:limit] if trimmed else None


def _clean_list(value, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        cleaned = _clean_str(item, item_limit)
        if cleaned:
            out.append(cleaned)
        if len(out) >= limit:
            break
    return out


_ENTITY_KEYS = ("product", "location", "staff", "dates")


def _clean_entities(value) -> dict:
    """Entities as a fixed shape, so downstream code never guesses at keys."""
    from .subjects import ENTITY_KEYS

    src = value if isinstance(value, dict) else {}
    return {k: _clean_list(src.get(k), 4, 80) for k in ENTITY_KEYS}


def is_human_corrected(meaning) -> bool:
    """True when a person has already set this meaning.

    Re-analysis must not overwrite it: a human looked at the review and made a
    call, and a later model pass has no way of knowing that.
    """
    return isinstance(meaning, dict) and meaning.get("source") == "human"
