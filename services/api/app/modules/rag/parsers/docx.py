from io import BytesIO

from docx import Document as DocxDocument


async def parse_docx(content: bytes) -> str:
    doc = DocxDocument(BytesIO(content))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(paragraphs)
