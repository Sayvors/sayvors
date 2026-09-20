"""Benchmarking / competitive intelligence — P4 pillar backend.

Two comparison layers, both real:
1. Branch vs branch (primary): the tenant's own locations ranked against
   each other on rating, sentiment, response rate, volume and reputation —
   with per-branch reasons and recommendations.
2. Tenant cohort (market view): the tenant's branches ranked against every
   other Sayvors-connected business in the same city + category. Tenants
   ARE the competitor set — no manual entry, no synthetic aggregates.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from .models import LocationDailyMetric, ReviewInsight
from .service import get_overview, reputation_score

logger = logging.getLogger(__name__)

SAUDI_CITIES = (
    "RIYADH", "JEDDAH", "DAMMAM", "MECCA", "MAKKAH", "MEDINA",
    "MADINAH", "KHOBAR", "AL KHOBAR", "DHAHRAN", "TAIF", "BURAIDAH",
    "TABUK", "ABHA", "JIZAN", "HAIL", "NAJRAN", "YANBU", "JUBAIL",
    "HOFUF", "AL AHSA", "AHSA", "QATIF", "KHAMIS", "ARAR", "SAKAKA",
    "DUBAI", "ABU DHABI", "SHARJAH", "AJMAN", "DOHA", "MANAMA", "KUWAIT",
)


def _parse_city(address: str | None) -> str | None:
    """City from a free-text listing address ("RIYADH Al Malqa Dist." → RIYADH).

    Matches a known Gulf-city list first (two-word names included); falls
    back to the raw leading token so identically-written addresses still
    group together. Never invents geography from junk.
    """
    if not address:
        return None
    cleaned = "".join(ch if ch.isalnum() or ch == " " else " " for ch in address)
    tokens = [t for t in cleaned.strip().split() if t]
    if not tokens:
        return None
    if len(tokens) > 1 and f"{tokens[0]} {tokens[1]}".upper() in SAUDI_CITIES:
        return f"{tokens[0]} {tokens[1]}".upper()
    first = tokens[0].upper()
    if first in SAUDI_CITIES:
        return first
    return first if len(first) >= 3 and first.isalpha() else None


def _median(values: list[float]) -> float | None:
    vals = sorted(values)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _recent(dt: datetime | None, cutoff: datetime) -> bool:
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt >= cutoff


async def _branch_breakdown(
    db: AsyncSession, user_id: str, days: int = 30
) -> list[dict]:
    """Per-branch scorecards, ranked by reputation (then review volume)."""
    from .intelligence import get_problems

    rows = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == user_id,
                Channel.platform == "google_reviews",
            )
        )
    ).scalars().all()

    branches: list[dict] = []
    for ch in rows:
        try:
            ov = await get_overview(db, user_id, ch.id, days)
        except Exception as e:
            logger.warning("Branch overview failed for %s: %s", ch.id, e)
            continue
        try:
            probs = (await get_problems(db, user_id, ch.id, days))["problems"]
            top = probs[0] if probs else None
        except Exception:
            top = None
        rep = ov.get("reputation_score") or reputation_score(
            ov.get("avg_rating", 0.0) or 0.0,
            ov.get("response_rate", 0.0) or 0.0,
            (ov.get("sentiment", {}) or {}).get("positive_pct", 0.0) / 100.0,
        )
        # — health, velocity, action rate: owner-centric signals —
        health = ov.get("health_score")
        if health is None:
            from .service import health_score as _health
            health = _health(
                ov.get("avg_rating", 0.0) or 0.0,
                (ov.get("response_rate", 0.0) or 0.0) / 100.0 if (ov.get("response_rate", 0.0) or 0.0) > 1 else (ov.get("response_rate", 0.0) or 0.0),
                (ov.get("sentiment", {}) or {}).get("positive_pct", 0.0) / 100.0,
                (ov.get("period", {}) or {}).get("velocity_ratio") or 1.0,
            )
        period = ov.get("period", {}) or {}
        gp = ov.get("google_performance", {}) or {}
        impressions = (gp.get("impressions_maps", 0) or 0)
        actions = (gp.get("customer_actions", 0) or 0)
        action_rate = round(actions / impressions * 100, 1) if impressions > 0 else None
        reviews_last_period = period.get("reviews", 0) or 0
        # annualised velocity (reviews/month) at current pace
        velocity_per_month = round(reviews_last_period * (30 / days), 1) if days else reviews_last_period
        branches.append({
            "channel_id": ch.id,
            "name": ch.display_name or "Location",
            "avg_rating": ov.get("avg_rating", 0.0) or 0.0,
            "reviews_total": ov.get("total_reviews", 0) or 0,
            "positive_pct": (ov.get("sentiment", {}) or {}).get("positive_pct", 0.0) or 0.0,
            "response_rate": round((ov.get("response_rate", 0.0) or 0.0) * 100, 1)
            if (ov.get("response_rate", 0.0) or 0.0) <= 1.0
            else round(ov.get("response_rate", 0.0) or 0.0, 1),
            "reputation_score": rep,
            "health_score": health,
            "rating_delta": period.get("rating_delta"),
            "reviews_delta_pct": period.get("reviews_delta_pct"),
            "velocity_ratio": period.get("velocity_ratio"),
            "reviews_last_period": reviews_last_period,
            "velocity_per_month": velocity_per_month,
            "impressions_maps": impressions,
            "customer_actions": actions,
            "action_rate": action_rate,
            "top_problem": (top or {}).get("name"),
            "top_problem_mentions": (top or {}).get("mentions", 0),
        })
    branches.sort(key=lambda b: (-b["reputation_score"], -b["reviews_total"]))
    for i, b in enumerate(branches):
        b["rank"] = i + 1
    # gap-widening math: how fast leader pulls away per year
    if branches:
        leader_vel = branches[0].get("velocity_per_month") or 0
        for b in branches:
            v = b.get("velocity_per_month") or 0
            gap_per_year = round((leader_vel - v) * 12, 0)
            b["gap_vs_leader_per_year"] = int(gap_per_year) if b["rank"] != 1 else 0
    return branches


def _distribution(branches: list[dict], key: str) -> dict | None:
    """Best / median / worst / gap for a numeric branch key."""
    vals = sorted([b[key] for b in branches if b.get(key) is not None], reverse=True)
    if not vals:
        return None
    n = len(vals)
    median = vals[n // 2] if n % 2 == 1 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    gap = vals[0] - vals[-1]
    return {"best": vals[0], "median": round(median, 1), "worst": vals[-1], "gap": round(gap, 1)}


async def _tenant_cohort(
    db: AsyncSession, user_id: str, days: int = 30
) -> dict:
    """You vs every other Sayvors business in your market.

    Tenants ARE the competitor set: each connected listing (any tenant but
    you) in the same city + business category becomes one ranked entry,
    using data already synced into this database (profile snapshot +
    insights). Scope widens city+category → city → whole network until it
    finds anyone; empty network returns an honest empty cohort.
    """
    from ..localith.models import LocalithConnection
    from ..users.models import User

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, days))

    me = await db.get(User, user_id)
    my_category = ((getattr(me, "business_type", None) or "").strip() or None) if me else None
    my_conns = (
        await db.execute(
            select(LocalithConnection).where(LocalithConnection.user_id == user_id)
        )
    ).scalars().all()
    city_counts: dict[str, int] = {}
    for c in my_conns:
        city = _parse_city(c.address)
        if city:
            city_counts[city] = city_counts.get(city, 0) + 1
    my_city = max(city_counts, key=city_counts.get) if city_counts else None

    all_conns = (
        await db.execute(select(LocalithConnection).order_by(LocalithConnection.created_at))
    ).scalars().all()
    other = [c for c in all_conns if c.user_id != user_id]
    if not other:
        return {"scope": "none", "label": "Sayvors network", "city": my_city,
                "category": my_category, "count": 0, "competitors": [],
                "user_ids": [],
                "median_rating": None, "median_reviews": None,
                "top3_median_rating": None, "median_response_rate": None,
                "median_positive_pct": None, "median_reputation": None}

    other_ids = list({c.user_id for c in other})
    users = {
        u.id: u
        for u in (
            await db.execute(select(User).where(User.id.in_(other_ids)))
        ).scalars().all()
    }

    def _cat(uid: str) -> str | None:
        u = users.get(uid)
        return ((getattr(u, "business_type", None) or "").strip() or None) if u else None

    levels: list[tuple[str, list]] = []
    if my_city and my_category:
        levels.append(("city_category", [
            c for c in other
            if _parse_city(c.address) == my_city
            and (_cat(c.user_id) or "").lower() == my_category.lower()
        ]))
    if my_city:
        levels.append(("city", [c for c in other if _parse_city(c.address) == my_city]))
    levels.append(("network", list(other)))

    scope, picked = next(((s, rows) for s, rows in levels if rows), ("none", []))
    picked = picked[:50]  # bounded: ranking stays instant at any network size

    # Channels + insights for the picked branches (batched, two queries).
    picked_ids = list({c.user_id for c in picked})
    ch_rows = (
        await db.execute(
            select(Channel).where(
                Channel.user_id.in_(picked_ids),
                Channel.platform == "google_reviews",
            )
        )
    ).scalars().all()
    chan_by_listing: dict[tuple[str, str], list[Channel]] = {}
    for ch in ch_rows:
        key = ch.listing_key or ""
        chan_by_listing.setdefault((ch.user_id, key), []).append(ch)
        chan_by_listing.setdefault((ch.user_id, (ch.display_name or "").lower()), []).append(ch)

    chan_ids = [ch.id for ch in ch_rows]
    insights: list[ReviewInsight] = []
    if chan_ids:
        insights = (
            await db.execute(
                select(ReviewInsight).where(ReviewInsight.channel_id.in_(chan_ids))
            )
        ).scalars().all()
    ins_by_chan: dict[str, list[ReviewInsight]] = {}
    for ins in insights:
        ins_by_chan.setdefault(ins.channel_id, []).append(ins)

    competitors: list[dict] = []
    for c in picked:
        chans = (chan_by_listing.get((c.user_id, c.listing_id))
                 or chan_by_listing.get((c.user_id, (c.listing_name or "").lower()))
                 or [])
        rows = [ins for ch in chans for ins in ins_by_chan.get(ch.id, [])]
        total = len(rows)
        replied = sum(1 for r in rows if r.replied)
        positives = sum(1 for r in rows if (r.sentiment or "") == "positive")
        response_rate = round(replied / total * 100, 1) if total else None
        positive_pct = positives / total if total else None
        velocity = round(sum(1 for r in rows if _recent(r.created_at, cutoff)) * (30 / days), 1) if days else 0
        competitors.append({
            "name": c.listing_name or "Nearby business",
            "city": _parse_city(c.address),
            "avg_rating": c.average_rating or 0.0,
            "reviews_total": c.total_reviews or 0,
            "response_rate": response_rate,
            "velocity_per_month": velocity,
            "positive_pct": round(positive_pct * 100, 1) if positive_pct is not None else None,
            "reputation_score": reputation_score(
                c.average_rating or 0.0,
                (response_rate / 100.0) if response_rate is not None else 0.0,
                positive_pct if positive_pct is not None else 0.5,
            ),
            "is_you": False,
            "listing_id": c.listing_id,
        })

    ratings = [e["avg_rating"] for e in competitors if e["avg_rating"] > 0] or [e["avg_rating"] for e in competitors]
    reviews = [e["reviews_total"] for e in competitors]
    responses = [e["response_rate"] for e in competitors if e["response_rate"] is not None]
    positives = [e["positive_pct"] for e in competitors if e["positive_pct"] is not None]
    reputations = [e["reputation_score"] for e in competitors]
    top3 = sorted(ratings, reverse=True)[:3]
    city_label = (my_city or "").title() if scope != "network" else ""
    if scope == "city_category":
        label = f"{city_label} {(my_category or '').lower()}"
    elif scope == "city":
        label = f"{city_label} businesses"
    else:
        label = "Sayvors network"
    return {
        "scope": scope,
        "label": label,
        "city": my_city,
        "category": my_category,
        "count": len(competitors),
        "competitors": competitors,
        "user_ids": sorted({c.user_id for c in picked}),
        "median_rating": round(_median(ratings) or 0.0, 2) if ratings else None,
        "median_reviews": int(_median(reviews) or 0) if reviews else None,
        "top3_median_rating": round(_median(top3) or 0.0, 2) if top3 else None,
        "median_response_rate": round(_median(responses) or 0.0, 1) if responses else None,
        "median_positive_pct": round(_median(positives) or 0.0, 1) if positives else None,
        "median_reputation": int(_median(reputations) or 0) if reputations else None,
    }


def _rank_market(mine: list[dict], theirs: list[dict]) -> tuple[list[dict], int | None]:
    """One ranked table, my branches flagged — same score both sides."""
    table = (
        [{**m, "is_you": True} for m in mine]
        + [{**t, "is_you": False} for t in theirs]
    )
    table.sort(key=lambda e: (-e.get("reputation_score", 0), -e.get("reviews_total", 0)))
    for i, e in enumerate(table):
        e["rank"] = i + 1
    my_rank = min([e["rank"] for e in table if e.get("is_you")], default=None)
    return table, my_rank


async def _cohort_complaints(db: AsyncSession, user_ids: list[str], days: int) -> list[str]:
    """Top complaint themes across cohort tenants (bounded, best-effort)."""
    from .intelligence import get_problems

    counts: dict[str, int] = {}
    for uid in user_ids[:5]:
        try:
            for p in (await get_problems(db, uid, None, days)).get("problems", [])[:4]:
                name = (p.get("name") or "").strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
        except Exception:
            continue
    return sorted(counts, key=counts.get, reverse=True)[:3]


async def _service_recommendations(
    db: AsyncSession, user_id: str, days: int
) -> dict:
    """Top services/products to promote vs fix, from intelligence."""
    try:
        from .intelligence import get_products, get_topics
        prods = (await get_products(db, user_id, None, days)).get("products", [])[:8]
        topics = (await get_topics(db, user_id, None, days)).get("topics", [])[:8]
    except Exception:
        return {"top_services": [], "needs_fix_services": [], "top_topics": []}
    top_services = []
    needs_fix = []
    for p in prods:
        name = p.get("name") or "Unknown"
        mentions = p.get("mentions", 0) or 0
        pos = p.get("positive_pct", 0) or 0
        neg = p.get("negative", 0) or 0
        avg = p.get("avg_rating")
        if mentions >= 2 and pos >= 70:
            top_services.append({"name": name, "mentions": mentions, "positive_pct": pos, "avg_rating": avg})
        if mentions >= 2 and (neg >= 2 or (100 - pos) >= 50):
            needs_fix.append({"name": name, "mentions": mentions, "positive_pct": pos, "avg_rating": avg, "negative": neg})
    top_services = sorted(top_services, key=lambda x: (-x["positive_pct"], -x["mentions"]))[:4]
    needs_fix = sorted(needs_fix, key=lambda x: (-x["negative"], -x["mentions"]))[:4]
    top_topics = sorted(topics, key=lambda x: -x.get("mentions", 0))[:4]
    return {"top_services": top_services, "needs_fix_services": needs_fix, "top_topics": top_topics}


def _branch_highlights(
    branches: list[dict],
) -> tuple[dict | None, dict | None, list[dict]]:
    """Leader + needs-attention spotlight and per-branch recommendations."""
    if not branches:
        return None, None, []
    rated = [b for b in branches if b["reviews_total"] > 0] or branches
    n = len(rated)
    avg_rating = sum(b["avg_rating"] for b in rated) / n
    avg_resp = sum(b["response_rate"] for b in rated) / n

    def _strengths(b: dict) -> list[str]:
        out = []
        if b["avg_rating"] >= avg_rating and b["avg_rating"] > 0:
            out.append(f"Highest guest love ({b['avg_rating']:.1f}★ avg)")
        if b["response_rate"] >= 100:
            out.append("Replies to every single review")
        elif b["response_rate"] >= avg_resp and b["response_rate"] > 0:
            out.append(f"Fastest responses ({b['response_rate']:.0f}% reply rate)")
        if (b["reviews_total"] or 0) > 0 and b["reviews_total"] >= max(
            (x["reviews_total"] or 0) for x in rated
        ):
            out.append(f"Most reviewed ({b['reviews_total']} reviews)")
        if (b.get("rating_delta") or 0) > 0:
            out.append(f"Rating climbing (+{b['rating_delta']:.1f}★ this period)")
        return out[:2]

    def _pains(b: dict) -> list[str]:
        out = []
        if b["avg_rating"] < 4.0 and b["avg_rating"] > 0:
            out.append(f"Below the 4.0★ visibility line ({b['avg_rating']:.1f}★)")
        if b["response_rate"] < 70:
            out.append(f"Only {b['response_rate']:.0f}% of reviews answered")
        if b.get("top_problem"):
            out.append(f"Guests keep mentioning “{b['top_problem']}” ({b.get('top_problem_mentions', 0)}×)")
        if (b.get("reviews_delta_pct") or 0) < 0:
            out.append("Review volume is shrinking")
        return out[:2]

    leader = rated[0]
    leader_out = {
        "channel_id": leader["channel_id"],
        "name": leader["name"],
        "reasons": _strengths(leader) or ["Steady all-round performance"],
    }
    attention = None
    if len(rated) > 1:
        worst = rated[-1]
        pains = _pains(worst)
        if pains:
            attention = {
                "channel_id": worst["channel_id"],
                "name": worst["name"],
                "reasons": pains,
            }

    recommendations: list[dict] = []
    for b in rated:
        pains = _pains(b)
        if pains and b is not leader:
            recommendations.append({
                "channel_id": b["channel_id"],
                "name": b["name"],
                "priority": "high" if b["avg_rating"] < 4.0 or b["response_rate"] < 50 else "medium",
                "text": f"Fix this first at {b['name']}: {pains[0].lower()}.",
            })
        elif b is leader:
            recommendations.append({
                "channel_id": b["channel_id"],
                "name": b["name"],
                "priority": "win",
                "text": f"Copy what works at {b['name']} to your other locations"
                + (f" — start with “{b['top_problem']}” fixes elsewhere." if b.get("top_problem") else "."),
            })
    if attention is None and len(rated) == 1:
        only = rated[0]
        recommendations.append({
            "channel_id": only["channel_id"],
            "name": only["name"],
            "priority": "medium",
            "text": f"Connect more locations to unlock branch-vs-branch comparison for {only['name']}.",
        })
    return leader_out, attention, recommendations[:6]


def _plain_summary(branches: list[dict], cur: dict, distribution: dict) -> str:
    """One-paragraph, non-technical read for the owner."""
    if not branches:
        return "Connect a location to see how your branches compare — then we will tell you where to send customers and what to fix."
    rated = [b for b in branches if b["reviews_total"] > 0]
    if not rated:
        return f"You have {len(branches)} locations connected but no reviews yet. Once Google syncs reviews, your best and weakest branches will appear here."
    leader = rated[0]
    worst = rated[-1] if len(rated) > 1 else None
    rep_gap = distribution.get("reputation", {}) or {}
    gap = rep_gap.get("gap", 0) if isinstance(rep_gap, dict) else 0
    parts = [f"{leader['name']} leads with {leader['reputation_score']} reputation ({leader['avg_rating']:.1f}★, {leader['response_rate']:.0f}% replies)."]
    if worst and len(rated) > 1:
        parts.append(f"{worst['name']} is {int(gap)} points behind — fix \"{worst.get('top_problem') or 'response rate'}\" there first.")
        if worst.get("gap_vs_leader_per_year") and worst["gap_vs_leader_per_year"] > 0:
            parts.append(f"At current pace, the gap widens by ~{worst['gap_vs_leader_per_year']} reviews a year.")
    if cur.get("google_performance", {}).get("impressions_maps", 0) > 0:
        ar = cur.get("google_performance", {}).get("customer_actions", 0) / max(1, cur["google_performance"]["impressions_maps"]) * 100
        if ar < 5:
            parts.append("Your views are not turning into calls — add a clear CTA and reply faster.")
        elif ar >= 8:
            parts.append("Your views are converting well into actions — keep it up.")
    return " ".join(parts)


async def get_benchmark(
    db: AsyncSession, user_id: str, channel_id: str | None, days: int = 30
) -> dict:
    cohort = await _tenant_cohort(db, user_id, days)
    cur = await get_overview(db, user_id, channel_id, days)
    branches = await _branch_breakdown(db, user_id, days)

    # Market table: my branches vs tenant cohort, one ranking.
    mine = [{
        "name": b["name"],
        "avg_rating": b["avg_rating"],
        "reviews_total": b["reviews_total"],
        "response_rate": b["response_rate"],
        "velocity_per_month": b.get("velocity_per_month") or 0,
        "reputation_score": b["reputation_score"],
        "channel_id": b["channel_id"],
    } for b in branches]
    market, my_rank = _rank_market(mine, cohort["competitors"])
    market_total = len(market)
    market_label = cohort["label"] if cohort["count"] else (
        f"{(cohort['city'] or '').title()} {(cohort['category'] or '').lower()}".strip()
        or "your market"
    )

    def _med(key: str, fallback: float) -> float:
        value = cohort.get(key)
        return float(value) if value is not None else float(fallback)

    similar_avg = _med("median_rating", cur["avg_rating"])
    similar_pos = _med("median_positive_pct", cur["sentiment"]["positive_pct"])
    similar_resp = _med("median_response_rate", cur["response_rate"])
    similar_rep = _med("median_reputation", cur["reputation_score"])

    outperforms = []
    underperforms = []
    if cur["avg_rating"] > similar_avg:
        outperforms.append("Average rating (%.1f vs %.1f)" % (cur["avg_rating"], similar_avg))
    else:
        underperforms.append("Average rating (%.1f vs %.1f)" % (cur["avg_rating"], similar_avg))

    if cur["sentiment"]["positive_pct"] > similar_pos:
        outperforms.append("Positive sentiment (%d%% vs %d%%)" % (cur["sentiment"]["positive_pct"], similar_pos))
    else:
        underperforms.append("Positive sentiment (%d%% vs %d%%)" % (cur["sentiment"]["positive_pct"], similar_pos))

    # Competitive opportunities: derive from gaps
    opps: list[str] = []
    if cur["response_rate"] < 70:
        opps.append("Improve response rate (currently %d%%) to lift reputation" % cur["response_rate"])
    if cur["google_performance"]["impressions_maps"] > 0 and cur["google_performance"]["customer_actions"] == 0:
        opps.append("Convert visibility into actions — add a clear CTA profile")
    if cur["sentiment"]["negative_pct"] > 20:
        opps.append("Address rising negative sentiment before it impacts visibility")
    if cur["period"]["reviews_delta_pct"] is not None and cur["period"]["reviews_delta_pct"] < 0:
        opps.append("Review volume is declining — ask happy customers for feedback")
    if not opps:
        opps.append("Keep promoting your best-rated products and maintain response speed")

    # Rank-based verdict against real tenants — never a synthetic average.
    if not cohort["count"]:
        benchmark_text = (
            f"You are the first {market_label} on Sayvors — "
            "every business that joins sharpens this view."
        )
        percentile_text = "No other businesses to rank against yet"
    elif not my_rank:
        benchmark_text = (
            f"{cohort['count']} {market_label} on Sayvors — "
            "connect a branch to enter the ranking."
        )
        percentile_text = f"{cohort['count']} {market_label} on Sayvors"
    elif my_rank == 1:
        benchmark_text = (
            f"You're #1 of {market_total} {market_label} on Sayvors — leading the pack."
        )
        percentile_text = f"Ranked #1 of {market_total} {market_label}"
    else:
        leader = market[0]
        gap = (leader["avg_rating"] or 0) - (cur["avg_rating"] or 0)
        benchmark_text = (
            f"You're #{my_rank} of {market_total} {market_label} on Sayvors"
            + (f" — {gap:.1f}★ behind {leader['name']}." if gap > 0 else ".")
        )
        percentile_text = f"Ranked #{my_rank} of {market_total} {market_label}"

    # Industry complaints: real themes across cohort tenants, not one account.
    common_complaints = await _cohort_complaints(db, cohort.get("user_ids", []), days)

    leader, attention, recommendations = _branch_highlights(branches)
    svc = await _service_recommendations(db, user_id, days)

    # — distribution & portfolio summary (owner-centric) —
    dist = {}
    for k in ("reputation_score", "avg_rating", "response_rate", "velocity_per_month"):
        d = _distribution(branches, k)
        if d:
            dist[k] = d
    # portfolio health / action rate
    total_impr = cur["google_performance"]["impressions_maps"]
    total_actions = cur["google_performance"]["customer_actions"]
    portfolio_action_rate = round(total_actions / total_impr * 100, 1) if total_impr > 0 else None
    portfolio_velocity_pm = round((cur["period"]["reviews"] or 0) * (30 / days), 1) if days else 0
    plain_summary = _plain_summary(branches, cur, dist)
    if cohort["count"] and my_rank:
        plain_summary += (
            f" You're #{my_rank} of {market_total} {market_label} on Sayvors."
        )

    # similar_* now read off the tenant cohort medians — real businesses,
    # never a synthetic account.
    median_reviews = cohort.get("median_reviews")
    return {
        "branches": branches,
        "leader": leader,
        "needs_attention": attention,
        "recommendations": recommendations,
        "top_services": svc["top_services"],
        "needs_fix_services": svc["needs_fix_services"],
        "top_topics": svc["top_topics"],
        "distribution": dist,
        "portfolio_health_score": cur.get("health_score"),
        "portfolio_action_rate": portfolio_action_rate,
        "portfolio_velocity_per_month": portfolio_velocity_pm,
        "portfolio_impressions": total_impr,
        "portfolio_actions": total_actions,
        "plain_summary": plain_summary,
        "days": days,
        "current_avg_rating": cur["avg_rating"],
        "similar_avg_rating": similar_avg,
        "current_reviews_total": cur["total_reviews"],
        "similar_reviews_total": int(median_reviews) if median_reviews is not None else cur["total_reviews"],
        "current_sentiment_positive_pct": cur["sentiment"]["positive_pct"],
        "similar_sentiment_positive_pct": similar_pos,
        "current_response_rate": cur["response_rate"],
        "similar_response_rate": similar_resp,
        "current_customer_actions": cur["google_performance"]["customer_actions"],
        "similar_customer_actions": cur["google_performance"]["customer_actions"],
        "current_reputation_score": cur["reputation_score"],
        "similar_reputation_score": similar_rep,
        "benchmark_text": benchmark_text,
        "percentile_text": percentile_text,
        "outperforms": outperforms,
        "underperforms": underperforms,
        "competitive_opportunities": opps[:3],
        "industry_trends": common_complaints,
        "cohort": {k: v for k, v in cohort.items() if k != "user_ids"},
        "market": market,
        "my_rank": my_rank,
    }