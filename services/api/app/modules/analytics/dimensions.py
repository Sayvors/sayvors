"""Standard business dimensions for the Review Intelligence scorecard.

One source of truth shared by:
  - the deterministic (heuristic) scorecard, which matches review text against
    these keyword seeds;
  - the LLM prompt, which names the standard keys so the model folds novel
    findings into them instead of inventing near-duplicates.

A dimension is bidirectional: the same dimension can carry praise and
complaints (e.g. "waited 30 minutes" and "served instantly"). The UI shows a
dimension only when at least one review mentioned it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DimensionDef:
    key: str
    label: str
    keywords: tuple[str, ...]


STANDARD_DIMENSIONS: tuple[DimensionDef, ...] = (
    DimensionDef(
        "credibility",
        "Credibility & Trust",
        (
            "honest", "honesty", "reliable", "trustworthy", "trust", "promise",
            "promised", "kept", "scam", "cheat", "overcharged", "transparent",
            "genuine", "real", "rip off", "ripoff", "fair", "genuinely",
        ),
    ),
    DimensionDef(
        "support",
        "Customer Support & Staff",
        (
            "staff", "service", "waiter", "waitress", "server", "cashier",
            "team", "employee", "manager", "owner", "helpful", "friendly",
            "professional", "welcoming", "attentive", "polite", "rude",
            "ignored", "unfriendly", "courteous", "hospitality", "ethics",
            "respectful", "greeted",
        ),
    ),
    DimensionDef(
        "speed",
        "Responsiveness & Speed",
        (
            "fast", "quick", "quickly", "rapid", "speedy", "slow", "wait",
            "waiting", "waited", "queue", "line", "delay", "delayed", "forever",
            "prompt", "instantly", "promptly", "hours wait", "took ages",
        ),
    ),
    DimensionDef(
        "quality",
        "Product/Service Quality",
        (
            "quality", "fresh", "taste", "tasty", "delicious", "flavor",
            "flavour", "cold", "stale", "burnt", "portion", "craft", "well made",
            "well-made", "amazing food", "cooked", "perfect", "excellent food",
            "authentic", "ingredients", "juicy", "crispy", "dry",
        ),
    ),
    DimensionDef(
        "value",
        "Value for Money",
        (
            "price", "prices", "value", "expensive", "cheap", "worth", "affordable",
            "overpriced", "cost", "charge", "charged", "portion size", "good value",
            "deal", "bargain", "money",
        ),
    ),
    DimensionDef(
        "environment",
        "Cleanliness & Environment",
        (
            "clean", "cleanliness", "dirty", "messy", "spotless", "tidy", "hygiene",
            "filthy", "atmosphere", "ambience", "ambiance", "decor", "music",
            "noisy", "cozy", "vibe", "seating", "room", "bathroom",
        ),
    ),
)

DIMENSION_BY_KEY: dict[str, DimensionDef] = {d.key: d for d in STANDARD_DIMENSIONS}


def _compile(def_: DimensionDef) -> re.Pattern[str]:
    """Word-boundary matcher.

    Naive substring matching produced false positives that made the scorecard
    look broken: the credibility keyword "real" matched "really", so a chatty
    5★ review with no credibility signal at all scored as a credibility mention.
    Boundary matching keeps stems ("clean"/"cleanliness" are listed separately)
    from bleeding into unrelated words.
    """
    parts = [re.escape(k).replace(r"\ ", r"\s+") for k in def_.keywords]
    return re.compile(r"(?<![a-z])(?:" + "|".join(parts) + r")(?![a-z])")


_PATTERNS: dict[str, re.Pattern[str]] = {d.key: _compile(d) for d in STANDARD_DIMENSIONS}

#: Ratings that count as praise / complaint / neutral for a matched dimension.
POSITIVE_MIN_RATING = 4
NEGATIVE_MAX_RATING = 2


@dataclass
class DimensionScore:
    key: str
    label: str
    standard: bool = True
    mentions: int = 0
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    ratings: list[int] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)

    @property
    def avg_rating(self) -> float:
        return round(sum(self.ratings) / len(self.ratings), 1) if self.ratings else 0.0

    @property
    def positive_pct(self) -> int:
        judged = self.positive + self.negative
        return round((self.positive / judged) * 100) if judged else 0

    @property
    def confidence(self) -> str:
        if self.mentions >= 5:
            return "high"
        if self.mentions >= 3:
            return "medium"
        return "low"

    @property
    def signal(self) -> str:
        """Coarse direction shown on the card: strong / mixed / weak."""
        if self.negative == 0 and self.positive > 0:
            return "strong"
        if self.positive == 0 and self.negative > 0:
            return "weak"
        if self.positive_pct >= 70:
            return "strong"
        if self.positive_pct <= 30:
            return "weak"
        return "mixed"

    def verdict(self) -> str:
        """Rule-based sentence; never states a count the rows do not support."""
        if not self.mentions:
            return ""
        bits = []
        if self.positive:
            bits.append(f"{self.positive} review(s) praise it")
        if self.negative:
            bits.append(f"{self.negative} review(s) criticise it")
        joined = " · ".join(bits) if bits else "mentioned without clear sentiment"
        return f"{joined} (avg {self.avg_rating}★)."

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "standard": self.standard,
            "mentions": self.mentions,
            "positive": self.positive,
            "negative": self.negative,
            "avg_rating": self.avg_rating,
            "positive_pct": self.positive_pct,
            "signal": self.signal,
            "confidence": self.confidence,
            "verdict": self.verdict(),
            "evidence": self.evidence,
        }


def _clean_quote(text: str) -> str:
    """Trim a review down to a short quotable fragment (no ellipsis slicing)."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= 140:
        return cleaned
    cut = cleaned[:140].rsplit(" ", 1)[0]
    return (cut or cleaned[:140]) + "…"


def score_dimensions(rows: list[dict], evidence_limit: int = 2) -> list[dict]:
    """Deterministic scorecard: classify reviews into the standard dimensions.

    Returns only dimensions with at least one mention (the UI hides the rest),
    each with honest positive/negative counts, a rule-based verdict and up to
    `evidence_limit` verbatim quotes. Never invents dimension names.
    """
    scores: dict[str, DimensionScore] = {}

    for r in rows:
        text = (r.get("text") or "").lower()
        rating = int(r.get("rating") or 0)
        if not text:
            continue
        for d in STANDARD_DIMENSIONS:
            if not _PATTERNS[d.key].search(text):
                continue
            score = scores.setdefault(
                d.key,
                DimensionScore(key=d.key, label=d.label, standard=True),
            )
            score.mentions += 1
            score.ratings.append(rating)
            if rating >= POSITIVE_MIN_RATING:
                score.positive += 1
            elif rating <= NEGATIVE_MAX_RATING:
                score.negative += 1
            else:
                score.neutral += 1
            if len(score.evidence) < evidence_limit:
                score.evidence.append({"quote": _clean_quote(r.get("text")), "rating": rating})

    ordered = sorted(
        scores.values(),
        key=lambda s: (list(DIMENSION_BY_KEY).index(s.key) if s.standard else 99, -s.mentions),
    )
    return [s.to_dict() for s in ordered if s.mentions > 0]
