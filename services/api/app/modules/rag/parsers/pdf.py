import pypdfium2 as pdfium
from io import BytesIO


async def parse_pdf(content: bytes) -> str:
    doc = pdfium.PdfDocument(BytesIO(content))
    pages = []
    for page in doc:
        text = page.get_textpage().get_text_range()
        pages.append(text)
    return "\n\n".join(pages)
