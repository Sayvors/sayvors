from io import BytesIO

import openpyxl

# DoS guard: workbooks are zip containers — a bomb can expand to gigabytes.
MAX_XLSX_ROWS = 200_000


async def parse_xlsx(content: bytes) -> str:
    wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
    chunks = []
    rows_seen = 0
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows(values_only=True):
            if rows_seen >= MAX_XLSX_ROWS:
                break
            rows_seen += 1
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                row_text = " | ".join(cells)
                chunks.append(f"[{sheet_name}] {row_text}")
        if rows_seen >= MAX_XLSX_ROWS:
            break
    wb.close()
    return "\n".join(chunks)
