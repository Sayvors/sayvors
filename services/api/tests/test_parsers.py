"""Parser DoS caps: rows/pages/paragraph counts are attacker-controlled."""
import csv
import io

import pytest

from app.modules.rag.parsers import csv as csv_parser
from app.modules.rag.parsers import docx as docx_parser
from app.modules.rag.parsers import xlsx as xlsx_parser


def _csv_bytes(n_rows: int) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "city"])
    for i in range(n_rows):
        writer.writerow([f"row{i}", f"city{i}"])
    return buf.getvalue().encode()


@pytest.mark.asyncio
async def test_csv_row_cap(monkeypatch):
    monkeypatch.setattr(csv_parser, "MAX_CSV_ROWS", 5)
    out = await csv_parser.parse_csv(_csv_bytes(50))
    assert len(out.splitlines()) == 5


@pytest.mark.asyncio
async def test_xlsx_row_cap(monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    from io import BytesIO

    wb = openpyxl.Workbook()
    ws = wb.active
    for i in range(20):
        ws.append([f"r{i}", f"c{i}"])
    payload = BytesIO()
    wb.save(payload)

    monkeypatch.setattr(xlsx_parser, "MAX_XLSX_ROWS", 7)
    out = await xlsx_parser.parse_xlsx(payload.getvalue())
    assert len(out.splitlines()) == 7


@pytest.mark.asyncio
async def test_docx_paragraph_cap(monkeypatch):
    docx = pytest.importorskip("docx")
    from io import BytesIO

    document = docx.Document()
    for i in range(20):
        document.add_paragraph(f"para {i}")
    payload = BytesIO()
    document.save(payload)

    monkeypatch.setattr(docx_parser, "MAX_DOCX_PARAGRAPHS", 6)
    out = await docx_parser.parse_docx(payload.getvalue())
    assert len(out.splitlines()) == 6
