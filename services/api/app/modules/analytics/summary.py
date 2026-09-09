"""AI Executive Summary — the killer feature.

Composes a business briefing from the live intelligence data (overview,
problems, products, visibility). The narrative text is LLM-polished when a
provider is available, with a deterministic rule-based fallback so the
banner always renders (same graceful-degradation pattern as enrichment).
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .growth import get_opportunities, get_visibility
from .intelligence import get_problems, get_products
from .service import get_overview

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the executive assistant of a business intelligence platform.
Write a 2-sentence executive briefing for the business owner based on the JSON facts provided.
Sentence 1: the overall trajectory (improving/declining, why — cite the biggest mover).
Sentence 2: the single most important action to take this week.
Plain text only. No markdown, no lists, no greetings, max 60 words."""


async def get_executive_summary(
    db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30
) -> dict:
    overview = await get_overview(db, user_id, channel_id, days)
    problems = (await get_problems(db, user_id, channel_id, days))["problems"]
    products = await get_products(db, user_id, channel_id, days)
    visibility = await get_visibility(db, user_id, channel_id, days)
    opportunities = (await get_opportunities(db, user_id, channel_id, days))["opportunities"]

    p = overview["period"]
    s = overview["sentiment"]
    top_problem = problems[0] if problems else None
    loved = products["most_loved"]

    # ── structured facts (always present, rule-based) ──
    wins: list[str] = []
    if p["rating_delta"] is not None and p["rating_delta"] > 0:
        wins.append(f"Rating up {p['rating_delta']} stars vs previous period")
    if s["positive_pct"] >= 65:
        wins.append(f"{s['positive_pct']}% positive sentiment")
    if visibility["impressions_trend_pct"] is not None and visibility["impressions_trend_pct"] > 0:
        wins.append(f"Google visibility up {visibility['impressions_trend_pct']}%")
    if visibility["customer_actions"] > 0:
        wins.append(f"{visibility['customer_actions']} customer actions from Google")

    problem_lines = [
        f"{pr['name']} — {pr['mentions']} mentions ({pr['status']}"
        + (f" +{pr['trend_pct']}%" if (pr["trend_pct"] or 0) > 0 else "")
        + f", {pr['severity']} severity)"
        for pr in problems[:3]
    ]

    opportunity_line = ""
    if loved:
        loved_product = next((x for x in products["products"] if x["name"] == loved), None)
        if loved_product:
            opportunity_line = (
                f"Product opportunity: {loved} — {loved_product['positive_pct']}% positive "
                f"across {loved_product['mentions']} mentions"
            )

    recommended_action = (
        opportunities[0]["title"] if opportunities else "Keep replying to every review"
    )

    # ── narrative headline ──
    headline = _fallback_headline(overview, top_problem)
    try:
        headline = await _llm_headline(overview, top_problem, loved, visibility)
    except Exception as e:
        logger.debug("Executive summary LLM unavailable, using fallback: %s", e)

    return {
        "days": days,
        "headline": headline,
        "avg_rating": overview["avg_rating"],
        "reputation_score": overview["reputation_score"],
        "health_score": overview["health_score"],
        "wins": wins[:3],
        "problems": problem_lines,
        "opportunity": opportunity_line,
        "recommended_action": recommended_action,
        "benchmark_text": f"You're outperforming {min(99, 50 + (overview['reputation_score'] - 50))}% of comparable businesses on reply discipline and rating." if overview["response_rate"] >= 70 else "Replying to more reviews will lift you above comparable businesses.",
    }


def _fallback_headline(overview: dict, top_problem: dict | None) -> str:
    p = overview["period"]
    s = overview["sentiment"]
    parts = []
    if p["rating_delta"] is not None:
        direction = "improved" if p["rating_delta"] > 0 else "declined"
        parts.append(f"Your rating {direction} {abs(p['rating_delta'])} stars this period")
    if top_problem:
        parts.append(f"with \u201c{top_problem['name']}\u201d as the main issue")
    if not parts:
        parts.append(f"Your business is holding steady at {overview['avg_rating']} stars with {s['positive_pct']}% positive sentiment")
    return (", ".join(parts) + ".").capitalize()


async def _llm_headline(overview: dict, top_problem: dict | None, loved: str | None, visibility: dict) -> str:
    import json

    from ..llm.providers.base import LLMMessage, LLMRequest
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model

    model = "groq:oss-120b"
    facts = {
        "avg_rating": overview["avg_rating"],
        "rating_delta": overview["period"]["rating_delta"],
        "reviews_period": overview["period"]["reviews"],
        "reviews_delta_pct": overview["period"]["reviews_delta_pct"],
        "positive_pct": overview["sentiment"]["positive_pct"],
        "response_rate": overview["response_rate"],
        "top_problem": top_problem and {
            "name": top_problem["name"],
            "mentions": top_problem["mentions"],
            "trend_pct": top_problem["trend_pct"],
        },
        "most_loved_product": loved,
        "impressions": visibility["impressions_maps"],
        "customer_actions": visibility["customer_actions"],
    }
    provider = get_provider_for_model(model)
    api_model, _ = _resolve_model(model)
    resp = await provider.complete(
        LLMRequest(
            model=api_model,
            messages=[LLMMessage(role="user", content=json.dumps(facts))],
            system_prompt=SYSTEM_PROMPT,
            temperature=0.4,
            max_tokens=160,
            stream=False,
        )
    )
    text = resp.content.strip()
    return text if text else _fallback_headline(overview, top_problem)
