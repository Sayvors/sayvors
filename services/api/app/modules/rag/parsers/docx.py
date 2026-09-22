from io import BytesIO

from docx import Document as DocxDocument

# DoS guard: docx is a zip container; paragraph count is attacker-controlled.
MAX_DOCX_PARAGRAPHS = 100_000


async def parse_docx(content: bytes) -> str:
    doc = DocxDocument(BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs[:MAX_DOCX_PARAGRAPHS] if p.text.strip()]
    return "\n".join(paragraphs)
