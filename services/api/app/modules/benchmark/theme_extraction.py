"""Dynamic review-theme extraction with no predefined domain keywords.

The local extractor is the deterministic fallback and the evidence validator
for LLM output. Both paths count distinct reviews, attach real source quotes,
and expose the sample denominator so the UI never implies lifetime precision.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from statistics import median
from typing import Any

MAX_THEMES = 12
MIN_MENTIONS = 2
MIN_SAMPLE_SHARE = 0.02
MIN_THEME_WORDS = 2
MAX_NGRAM = 3
MAX_LABEL_LEN = 80
# Bump when extraction/normalization rules change so cached analyses rebuild.
THEME_EXTRACTOR_VERSION = 2

_EN_STOPWORDS = set(
    "a an and are as at be been being but by can could did do does for from had has have he her hers him his how i if in into is it its just me more most my no not of on or our ours out over really she should so some than that the their them then there these they this those through to too under up us very was we were what when where which who why will with would you your yours".split()
)
_AR_STOPWORDS = set(
    "من في على علي عن الى إلى أن إن ان مع هذا هذه ذلك تلك كان كانت يكون تكون قد لقد لم لن ما لا هل و أو ثم لكن أيضا أيضًا جدا جداً غير ليس ليست عند لدى هناك هنا الله له شركة شركه افضل أفضل ممتاز ممتازه ممتازة جديد جديده جديدا كل شيء شي".split()
)


def _strip_arabic_marks(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", value)
    return (
        value.replace("أ", "ا")
        .replace("إ", "ا")
        .replace("آ", "ا")
        .replace("ى", "ي")
        .replace("ة", "ه")
    )


def normalize_theme_key(value: str) -> str:
    """Comparison key only; displayed labels keep their original spelling."""
    value = _strip_arabic_marks(str(value or "").lower())
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())[:MAX_LABEL_LEN]


def _normalize_token(token: str) -> str:
    token = _strip_arabic_marks(token)
    # Arabic reviews alternate between "الخدمة" and "خدمة". The definite
    # article is not a distinct theme, but the displayed surface keeps it.
    if len(token) > 3 and token.startswith("ال"):
        token = token[2:]
    return token


def _token_pairs(value: str) -> list[tuple[str, str]]:
    raw = re.findall(r"[^\W_]+", str(value or "").lower(), flags=re.UNICODE)
    pairs: list[tuple[str, str]] = []
    for surface in raw:
        normalized = _normalize_token(surface)
        if len(normalized) > 1 and normalized not in _EN_STOPWORDS and normalized not in _AR_STOPWORDS:
            pairs.append((surface, normalized))
    return pairs


def _tokens(value: str) -> list[str]:
    return [normalized for _surface, normalized in _token_pairs(value)]


def _review_sentiment(review: dict[str, Any]) -> str:
    stored = str(review.get("sentiment") or "").lower()
    if stored in {"positive", "neutral", "negative"}:
        return stored
    rating = review.get("rating")
    if rating is None:
        return "neutral"
    try:
        value = float(rating)
    except (TypeError, ValueError):
        return "neutral"
    if value >= 4:
        return "positive"
    if value == 3:
        return "neutral"
    return "negative"


def _surface_label(normalized: str, surfaces: Counter[str]) -> str:
    return surfaces.most_common(1)[0][0] if surfaces else normalized


def _example(review: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": review.get("review_id"),
        "text": str(review.get("text") or "")[:600],
        "author": review.get("author"),
        "rating": review.get("rating"),
        "time": review.get("time"),
        "answered": bool(review.get("answered")),
        "review_url": review.get("review_url"),
    }


def _build_theme(
    label: str,
    mentions: int,
    sample_size: int,
    reviews: list[dict[str, Any]],
    *,
    normalized: str | None = None,
) -> dict[str, Any]:
    normalized = normalized or normalize_theme_key(label)
    counts = Counter(_review_sentiment(review) for review in reviews)
    dominant = counts.most_common(1)[0][0] if counts else "neutral"
    return {
        "label": label,
        "normalized": normalized,
        "sentiment": dominant,
        "mentions": mentions,
        "sample_size": sample_size,
        "pct": round(mentions / sample_size * 100, 1) if sample_size else 0.0,
        "positive_mentions": counts.get("positive", 0),
        "neutral_mentions": counts.get("neutral", 0),
        "negative_mentions": counts.get("negative", 0),
        "examples": [_example(review) for review in reviews[:2]],
    }


def extract_local_themes(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract repeated 1–3 word phrases from review text.

    Candidate vocabulary is entirely data-driven. Only function words are
    removed; there is no restaurant/software/etc. keyword list.
    """
    sample = [review for review in reviews if str(review.get("text") or "").strip()]
    sample_size = len(sample)
    if sample_size < MIN_MENTIONS:
        return []

    document_frequency: Counter[str] = Counter()
    surfaces: dict[str, Counter[str]] = defaultdict(Counter)
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for review in sample:
        pairs = _token_pairs(review.get("text"))
        if not pairs:
            continue
        tokens = [normalized for _surface, normalized in pairs]
        surface_tokens = [surface for surface, _normalized in pairs]
        seen_in_review: set[str] = set()
        for size in range(MIN_THEME_WORDS, MAX_NGRAM + 1):
            for start in range(0, len(tokens) - size + 1):
                phrase = tokens[start : start + size]
                surface = " ".join(surface_tokens[start : start + size])
                normalized = normalize_theme_key(" ".join(sorted(phrase)) if size > 1 else phrase[0])
                if not normalized or normalized in seen_in_review:
                    continue
                seen_in_review.add(normalized)
                document_frequency[normalized] += 1
                surfaces[normalized][surface] += 1
                evidence[normalized].append(review)

    ranked: list[tuple[float, str]] = []
    for normalized, count in document_frequency.items():
        if count < MIN_MENTIONS or count / sample_size < MIN_SAMPLE_SHARE:
            continue
        words = len(normalized.split())
        score = count * (1 + 0.25 * (words - 1))
        ranked.append((score, normalized))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    # Prefer the most specific repeated phrase when a shorter phrase adds no
    # extra evidence. "slow service" beats "service" when both occur in the
    # exact same reviews; this keeps the local fallback readable.
    candidates = [key for _score, key in ranked]
    selected_keys: list[str] = []
    for _score, normalized in ranked:
        words = normalized.split()
        if len(words) < MAX_NGRAM and any(
            len(other.split()) > len(words)
            and set(words).issubset(other.split())
            and document_frequency[other] == document_frequency[normalized]
            for other in candidates
        ):
            continue
        selected_keys.append(normalized)
        if len(selected_keys) >= MAX_THEMES:
            break

    themes: list[dict[str, Any]] = []
    for normalized in selected_keys:
        label = _surface_label(normalized, surfaces[normalized])
        themes.append(_build_theme(label, document_frequency[normalized], sample_size, evidence[normalized], normalized=normalized))
    return themes


def _label_evidence_overlap(label: str, review_text: str) -> bool:
    label_tokens = set(_tokens(label))
    if not label_tokens:
        return False
    review_tokens = set(_tokens(review_text))
    return len(label_tokens & review_tokens) >= max(1, len(label_tokens) // 2)


def validate_llm_themes(
    payload: Any,
    reviews: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Validate LLM themes against real review indices.

    The model proposes labels and counts; the server owns evidence, sentiment,
    percentages, and deduplication. Any hallucinated count/index rejects the
    payload so the caller can use the deterministic local extractor.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("themes"), list):
        return None
    sample = [review for review in reviews if str(review.get("text") or "").strip()]
    if len(sample) < MIN_MENTIONS:
        return []
    accepted: dict[str, dict[str, Any]] = {}
    for item in payload["themes"][: MAX_THEMES * 2]:
        if not isinstance(item, dict):
            return None
        label = str(item.get("label") or "").strip()
        normalized = normalize_theme_key(label)
        mentions = item.get("mentions")
        indices = item.get("review_indices")
        if not normalized or len(label) > MAX_LABEL_LEN or len(normalized.split()) < MIN_THEME_WORDS:
            return None
        if not isinstance(mentions, int) or isinstance(mentions, bool):
            return None
        if mentions < MIN_MENTIONS or mentions > len(sample):
            return None
        if mentions / len(sample) < MIN_SAMPLE_SHARE:
            continue
        if not isinstance(indices, list) or len(indices) != mentions:
            return None
        if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(sample) for index in indices):
            return None
        if len(set(indices)) != mentions:
            return None
        selected = [sample[index] for index in indices]
        matching = sum(_label_evidence_overlap(label, review.get("text")) for review in selected)
        if matching != mentions:
            return None
        theme = _build_theme(label, mentions, len(sample), selected, normalized=normalized)
        existing = accepted.get(normalized)
        if existing is None or theme["mentions"] > existing["mentions"]:
            accepted[normalized] = theme
    return sorted(accepted.values(), key=lambda theme: (-theme["mentions"], theme["label"]))[:MAX_THEMES]


def group_theme_comparison(
    subjects: list[dict[str, Any]],
    *,
    own_key: str | None,
) -> list[dict[str, Any]]:
    """Merge identical normalized themes across the selected businesses."""
    groups: dict[str, dict[str, Any]] = {}
    for subject in subjects:
        for theme in subject.get("themes") or []:
            normalized = normalize_theme_key(theme.get("normalized") or theme.get("label"))
            if not normalized:
                continue
            group = groups.setdefault(
                normalized,
                {"label": theme.get("label") or normalized, "sentiment": theme.get("sentiment") or "neutral", "cells": {}},
            )
            group["cells"][subject["key"]] = theme

    rows: list[dict[str, Any]] = []
    for normalized, group in groups.items():
        cells = group["cells"]
        own = cells.get(own_key) if own_key else None
        if own:
            group["label"] = own.get("label") or group["label"]
            group["sentiment"] = own.get("sentiment") or group["sentiment"]
        peer_pcts = [cell.get("pct") for key, cell in cells.items() if key != own_key and cell.get("pct") is not None]
        peer_median = median(peer_pcts) if peer_pcts else None
        own_pct = own.get("pct") if own else None
        rows.append({
            "key": normalized,
            "label": group["label"],
            "sentiment": group["sentiment"],
            "cells": cells,
            "own_pct": own_pct,
            "peer_median_pct": round(peer_median, 1) if peer_median is not None else None,
            "gap_pct": round(own_pct - peer_median, 1) if own_pct is not None and peer_median is not None else None,
            "max_mentions": max((cell.get("mentions") or 0 for cell in cells.values()), default=0),
        })
    rows.sort(key=lambda row: (-row["max_mentions"], -abs(row["gap_pct"] or 0), row["label"]))
    return rows

