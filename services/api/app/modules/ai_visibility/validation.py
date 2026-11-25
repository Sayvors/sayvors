"""Validate LLM claims against immutable fetched source snapshots."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from .research import ResearchPayload

CITATION_RE = re.compile(r"\[(S\d+)\]")
PHONE_RE = re.compile(r"\+?\d[\d\s\-()]{7,}\d")


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


def validate(
    payload: ResearchPayload, sources: list[dict], branch: dict
) -> ResearchPayload:
    """Ground citations and recompute outcomes without trusting model flags."""
    by_label = {row["label"]: row for row in sources}
    answer_labels = set(CITATION_RE.findall(payload.answer))
    if not answer_labels.issubset(by_label):
        raise CitationValidationError("fabricated_answer_citation")

    contradicted = False
    for claim in payload.claims:
        if not _quote_is_grounded(claim.quote, claim.source_ids, by_label):
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
            _domain(row.get("url")) == domain
            or _domain(row.get("url")).endswith(f".{domain}")
            for row in sources
        )
    )

    payload.mentioned = mentioned
    payload.cited = cited
    payload.recommended = payload.recommended and mentioned
    payload.incorrect = (
        contradicted
        or payload.incorrect
        or bool(branch_phone and phones and branch_phone not in phones)
    )
    payload.competitors = [
        row
        for row in payload.competitors
        if row.source_ids
        and set(row.source_ids).issubset(by_label)
        and _quote_is_grounded(row.quote, row.source_ids, by_label)
    ]
    return payload
