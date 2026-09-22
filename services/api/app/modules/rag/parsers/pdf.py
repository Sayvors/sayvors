import pypdfium2 as pdfium
from io import BytesIO

# DoS guard: page count is attacker-controlled via the PDF catalog.
MAX_PDF_PAGES = 1_000


async def parse_pdf(content: bytes) -> str:
    doc = pdfium.PdfDocument(BytesIO(content))
    pages = []
    for page in doc:
        if len(pages) >= MAX_PDF_PAGES:
            break
        text = page.get_textpage().get_text_range()
        pages.append(text)
    return "\n\n".join(pages)
