"""Chunking for RAG ingest (§31 Phase B: heading-aware with metadata).

Markdown is split on headings first so a chunk never bleeds across sections —
a hit on "pricing" then returns the chunk titled "Pricing › Annual plan"
instead of a random paragraph. Within a section the text is sentence-split
with overlap, matching the previous behaviour for plain (non-markdown)
documents such as extracted PDFs and CSVs.

Every chunk carries ``metadata`` (section trail, position, plus lang/source
attached by the caller) which ``DocumentChunk.metadata_`` persists and
``hybrid_search`` already surfaces.
"""
import re

# Headings: markdown ATX (# .. ######). Setext (===/---) is not matched on
# purpose: ---- rows are common in tables and would shred them.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_SENTENCE_RE = re.compile(r"(?<=[.!?؟])\s+")


def _split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_RE.split(text.strip()) if s.strip()]


def _make_chunks(
    text: str,
    metadata: dict,
    max_tokens: int,
    overlap_tokens: int,
) -> list[dict]:
    """Sentence-split one section into bounded, overlapping chunks."""
    chunks: list[dict] = []
    parts: list[str] = []
    current_tokens = 0

    for sentence in _split_sentences(text):
        sentence_tokens = len(sentence.split())
        if current_tokens + sentence_tokens > max_tokens and parts:
            chunks.append({
                "content": " ".join(parts),
                "token_count": current_tokens,
                "metadata": {**metadata, "index": len(chunks)},
            })
            keep = max(1, overlap_tokens // 50)
            parts = parts[keep:]
            current_tokens = sum(len(p.split()) for p in parts)
        parts.append(sentence)
        current_tokens += sentence_tokens

    if parts:
        chunks.append({
            "content": " ".join(parts),
            "token_count": current_tokens,
            "metadata": {**metadata, "index": len(chunks)},
        })
    return chunks


def chunk_markdown(
    text: str,
    max_tokens: int = 1000,
    overlap_tokens: int = 150,
    base_metadata: dict | None = None,
) -> list[dict]:
    """Heading-aware chunking for markdown documents.

    The heading trail (e.g. ``"Guide › Pricing › Annual"``) rides on every
    chunk from that section, giving search results a stable, human title.
    """
    base = dict(base_metadata or {})
    lines = text.split("\n")

    sections: list[tuple[list[str], str]] = []  # (heading_trail, body)
    trail: list[str] = []
    body: list[str] = []

    def _flush() -> None:
        joined = "\n".join(body).strip()
        if joined:
            sections.append((list(trail), joined))
        body.clear()

    for line in lines:
        match = _HEADING_RE.match(line.strip())
        if match:
            _flush()
            level = len(match.group(1))
            heading = match.group(2).strip()
            trail = trail[: level - 1]
            trail.append(heading)
        else:
            body.append(line)
    _flush()

    if not sections:
        # No headings at all — behave like plain text.
        return _make_chunks(text, {"section": None}, max_tokens, overlap_tokens)

    chunks: list[dict] = []
    for trail_parts, section_text in sections:
        section_name = " › ".join(trail_parts) if trail_parts else None
        chunks.extend(_make_chunks(
            section_text,
            {"section": section_name},
            max_tokens,
            overlap_tokens,
        ))
    if base:
        for chunk in chunks:
            chunk["metadata"] = {**base, **chunk["metadata"]}
    return chunks


def chunk_text(
    text: str,
    max_tokens: int = 1000,
    overlap_tokens: int = 150,
    metadata: dict | None = None,
) -> list[dict]:
    """Chunk any document. Markdown goes through the heading-aware path;
    plain text (PDF/CSV extracts) keeps the flat sentence splitter."""
    if not text or not text.strip():
        return []
    looks_like_markdown = bool(re.search(r"(?m)^#{1,6}\s+\S", text))
    if looks_like_markdown:
        return chunk_markdown(text, max_tokens, overlap_tokens, metadata)
    return _make_chunks(text, dict(metadata or {"section": None}), max_tokens, overlap_tokens)
