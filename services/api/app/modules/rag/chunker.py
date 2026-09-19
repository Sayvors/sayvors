import re


def chunk_text(text: str, max_tokens: int = 1000, overlap_tokens: int = 150) -> list[dict]:
    if not text or not text.strip():
        return []

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks: list[dict] = []
    current_parts: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = len(sentence.split())
        if current_tokens + sentence_tokens > max_tokens and current_parts:
            chunk_content = " ".join(current_parts)
            chunks.append({
                "content": chunk_content,
                "token_count": current_tokens,
            })
            overlap_start = max(0, len(current_parts) - max(1, overlap_tokens // 50))
            current_parts = current_parts[overlap_start:]
            current_tokens = sum(len(p.split()) for p in current_parts)

        current_parts.append(sentence)
        current_tokens += sentence_tokens

    if current_parts:
        chunk_content = " ".join(current_parts)
        chunks.append({
            "content": chunk_content,
            "token_count": current_tokens,
        })

    return chunks
