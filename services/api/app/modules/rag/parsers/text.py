import re


async def parse_text(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    return re.sub(r"\n{3,}", "\n\n", text).strip()
