"""Validate LLM claims against immutable fetched source snapshots."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .research import ResearchPayload

CITATION_RE = re.compile(r"\[(S\d+)\]")
PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")
URL_RE = re.compile(r"https?://[^\s<>()\[\]]+")
SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
RECOMMENDATION_RE = re.compile(
    r"\b(recommend|recommended|best|top|favorite|favourite|preferred)\b|موصى|موصى به|أفضل|أنصح|مفضل",
    re.I,
)


class CitationValidationError(ValueError):
    pass


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _domain(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").casefold().removeprefix("www.")


def _normalize_phone(value: str) -> str:
    return re.sub(r"\D", "", value)


def _quote_is_grounded(quote: str, source_ids: list[str], by_label: dict) -> bool:
    normalized_quote = _normalize(quote)
    return bool(normalized_quote) and any(
        normalized_quote in _normalize(by_label[label].get("excerpt") or "")
        for label in source_ids
        if label in by_label
    )


def _text_in_sources(text: str, source_ids: list[str], by_label: dict) -> bool:
    normalized = _normalize(text).strip(" .!?。！？:：")
    return bool(normalized) and any(
        normalized in _normalize(by_label[label].get("excerpt") or "")
        for label in source_ids
        if label in by_label
    )


def _claim_is_grounded(
    claim: str, quote: str, source_ids: list[str], by_label: dict
) -> bool:
    """Require one mapped source to contain both the claim and its exact quote."""
    if not source_ids or not set(source_ids).issubset(by_label):
        return False
    return any(
        _quote_is_grounded(quote, [label], by_label)
        and _text_in_sources(claim, [label], by_label)
        for label in source_ids
    )


def _validate_answer(answer: str, by_label: dict) -> None:
    source_urls = {str(row.get("url") or "").rstrip(".,;:!?") for row in by_label.values()}
    for raw_url in URL_RE.findall(answer):
        if raw_url.rstrip(".,;:!?") not in source_urls:
            raise CitationValidationError("unfetched_answer_url")
    for sentence in SENTENCE_RE.split(answer):
        labels = set(CITATION_RE.findall(sentence))
        if not labels:
            raise CitationValidationError("uncited_answer_sentence")
        if not labels.issubset(by_label):
            raise CitationValidationError("fabricated_answer_citation")
        factual_text = CITATION_RE.sub("", sentence)
        if not _text_in_sources(factual_text, labels, by_label):
            raise CitationValidationError("ungrounded_answer_sentence")


def validate(
    payload: ResearchPayload, sources: list[dict], branch: dict
) -> ResearchPayload:
    """Ground citations and recompute outcomes without trusting model flags."""
    by_label = {row["label"]: row for row in sources}
    _validate_answer(payload.answer, by_label)

    contradicted = False
    for claim in payload.claims:
        if not _claim_is_grounded(
            claim.claim, claim.quote, claim.source_ids, by_label
        ):
            claim.status = "unsupported"
            continue
        branch_phone = _normalize_phone(str(branch.get("phone") or ""))
        claim_phones = {
            _normalize_phone(match.group()) for match in PHONE_RE.finditer(claim.claim)
        }
        if branch_phone and claim_phones and branch_phone not in claim_phones:
            claim.status = "contradicted"
            contradicted = True
        else:
            claim.status = "supported"

    answer = _normalize(payload.answer)
    answer_labels = set(CITATION_RE.findall(payload.answer))
    name = _normalize(str(branch.get("name") or ""))
    domain = _domain(branch.get("website"))
    phones = {
        _normalize_phone(match.group()) for match in PHONE_RE.finditer(answer)
    }
    branch_phone = _normalize_phone(str(branch.get("phone") or ""))
    mentioned = bool(
        (name and name in answer)
        or (domain and re.search(rf"(?<![\w.-]){re.escape(domain)}(?![\w.-])", answer))
        or (branch_phone and branch_phone in phones)
    )
    cited = bool(
        domain
        and any(
            label in answer_labels
            and (
                _domain(row.get("url")) == domain
                or _domain(row.get("url")).endswith(f".{domain}")
            )
            for label, row in by_label.items()
        )
    )

    payload.mentioned = mentioned
    payload.cited = cited
    payload.recommended = bool(
        mentioned
        and name
        and any(
            claim.status == "supported"
            and name in _normalize(claim.claim)
            and RECOMMENDATION_RE.search(claim.claim)
            for claim in payload.claims
        )
    )
    payload.incorrect = contradicted or bool(
        branch_phone and phones and branch_phone not in phones
    )
    payload.competitors = [
        row
        for row in payload.competitors
        if row.source_ids
        and set(row.source_ids).issubset(by_label)
        and _normalize(row.name) in _normalize(row.quote)
        and _quote_is_grounded(row.quote, row.source_ids, by_label)
    ]
    return payload
