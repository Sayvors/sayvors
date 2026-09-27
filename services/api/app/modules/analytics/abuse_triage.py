"""AI triage for reviews a merchant flagged as abusive.

Scope is deliberately narrow: score how likely a review breaches Google's
Business Profile content policies, and say why. It is advisory only.

Design rules, all of them learned the hard way from the rest of this codebase:
  * The model never decides. `abuse_verdict` stays None until a human sets it.
  * It never auto-reports. Google's API cannot file a report anyway, and a
    false accusation on a public listing is expensive for a small business.
  * A failure returns a neutral result, never an accusation. A broken LLM must
    not leave "abusive" sitting on a review a human has to clear.
  * Output is verified against the review actually passed in — a model that
    hallucinates a quote or a confidence outside 0..1 is rejected.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You assess whether a single customer review violates Google's \
Business Profile content policies. You are advising a small business owner, \
so false accusations are costly.

Google's policies prohibit: spam or fake engagement, content unrelated to the \
business, harassment, profanity or hate speech, sexual content, illegal content, \
and conflicts of interest (a competitor's review, or a review from someone with \
a personal stake).

Guidelines:
- Judging the REVIEW, never the reviewer. A rude review about a real visit is \
not harassment; a genuine complaint is not a policy violation.
- Profanity alone is usually NOT a violation unless it is targeted abuse.
- Being negative about the business is NOT a violation. Most negative reviews \
are legitimate.
- If the review is merely a complaint, the score must be low.
- Only quote text that appears verbatim in the review.

Return JSON only:
{"score": <float 0..1 probability of a policy violation>,
 "labels": [<short snake_case labels>],
 "rationale": "<one or two sentences, plain language>"}"""


class AbuseAssessment(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    labels: list[str] = Field(default_factory=list)
    rationale: str = ""


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json(text: str) -> dict | None:
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return None


async def assess_review(
    *,
    text: str | None,
    rating: int,
    reviewer_name: str | None = None,
    model: str = "openai:gpt-4o-mini",
    tenant_id: str | None = None,
) -> AbuseAssessment | None:
    """Score one review. Returns None when no verdict could be reached.

    None means "unknown" — the caller must leave the review unflagged rather
    than assume the worst.
    """
    body = (text or "").strip()
    if not body:
        # Nothing to assess. An empty comment carries no signal either way.
        return None

    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model

    try:
        provider = get_provider_for_model(model)
        api_model, _ = _resolve_model(model)
        resp = await provider.complete(
            LLMRequest(
                model=api_model,
                messages=[LLMMessage(role="user", content=json.dumps({
                    "rating": rating,
                    "review_text": body,
                    "reviewer_name": reviewer_name,
                }))],
                system_prompt=SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=400,
                stream=False,
                tenant_id=tenant_id,
                model_id=model,
                purpose="analytics.abuse_triage",
            )
        )
    except Exception as e:
        logger.warning("abuse triage LLM call failed: %s", e)
        return None

    payload = _extract_json(resp.content or "")
    if payload is None:
        logger.warning("abuse triage returned unparseable output")
        return None
    try:
        parsed = AbuseAssessment.model_validate(payload)
    except ValidationError as e:
        # A score outside 0..1 means the output is not trustworthy; drop it
        # rather than clamping, which would invent a verdict.
        logger.warning("abuse triage output failed validation: %s", e)
        return None

    # Reject hallucinated quotes — the rationale must not invent review text.
    # 12 chars is long enough to be a real phrase rather than an article, so
    # ordinary quoted fragments from the review still pass.
    quoted = re.findall(r"[\"“']([^\"”']{12,})[\"”']", parsed.rationale)
    for quote in quoted:
        if quote.strip().lower() not in body.lower():
            logger.warning("abuse triage rationale contained a fabricated quote; dropped")
            return None

    parsed.labels = [str(x)[:40] for x in (parsed.labels or [])][:6]
    parsed.rationale = (parsed.rationale or "")[:600]
    return parsed


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
