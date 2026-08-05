import csv
from io import StringIO


async def parse_csv(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(StringIO(text))
    chunks = []
    for row in reader:
        items = [f"{k}={v}" for k, v in row.items() if v]
        if items:
            chunks.append(", ".join(items))
    return "\n".join(chunks)
