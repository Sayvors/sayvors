"""Shared multilingual text normalization and tokenization.

Used by relevance assessment, domain vocabulary, offer matching, and the
validator. The goal is to stop duplicating ``[a-z0-9]`` regexes (which silently
drop every non-Latin script) and to give every caller one Unicode-aware
tokenizer.

Design rules:
- Normalize for *matching*, never for display. The original text is preserved
  by callers; this module only produces comparison keys.
- Language-agnostic: works for Arabic, Urdu, Latin, CJK, etc.
- Conservative stemming: prefix overlap, not aggressive morphological analysis.
  False positives here cause false "on_topic" verdicts, which are safer than
  false "off_topic" (which sends legitimate reviews to human review).
"""
from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str | None) -> str:
    """NFKC-normalize, casefold, strip Arabic diacritics/tatweel, fold alef/ya."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = t.casefold()
    # Arabic diacritics (harakat) + tatweel + alef variants.
    t = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", t)
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ٱ", "ا")
    t = t.replace("ى", "ي").replace("ة", "ه")
    # Collapse whitespace.
    t = re.sub(r"\s+", " ", t).strip()
    return t


def tokens(text: str | None, min_len: int = 2) -> list[str]:
    """Unicode-aware word tokens, min length ``min_len``.

    For CJK (no spaces), fall back to character bigrams so we still get
    comparable tokens.
    """
    if not text:
        return []
    t = normalize_text(text)
    # Word chars except underscore, Unicode-aware.
    toks = re.findall(r"[^\W_]{%d,}" % min_len, t)
    if toks:
        return toks
    # CJK fallback: character bigrams.
    chars = [c for c in t if c.strip()]
    if len(chars) >= 2:
        return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]
    return chars


def term_hit(term: str, domain: set[str]) -> bool:
    """Conservative match of one term against a domain token set.

    Exact match, or a 4-char prefix overlap (handles plurals like بيتزا/بيتزات).
    """
    term = normalize_text(term)
    if not term or term in domain:
        if term in domain:
            return True
    # Single-token terms only.
    toks = tokens(term, min_len=2)
    if not toks:
        return False
    term_tok = toks[0]
    for dw in domain:
        if dw == term_tok:
            return True
        if len(dw) >= 4 and len(term_tok) >= 4:
            if dw[:4] == term_tok[:4]:
                return True
    return False


def contains_phrase(text: str | None, phrase: str | None) -> bool:
    """Whether ``phrase`` (normalized) appears as a substring of ``text``."""
    if not text or not phrase:
        return False
    return normalize_text(phrase) in normalize_text(text)