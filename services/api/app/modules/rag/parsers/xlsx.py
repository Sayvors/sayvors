from io import BytesIO

import openpyxl


async def parse_xlsx(content: bytes) -> str:
    wb = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
    chunks = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                row_text = " | ".join(cells)
                chunks.append(f"[{sheet_name}] {row_text}")
    wb.close()
    return "\n".join(chunks)
