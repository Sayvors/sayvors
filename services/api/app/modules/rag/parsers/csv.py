import csv
from io import StringIO

# DoS guard: a small CSV can explode into huge text; stop well before that.
MAX_CSV_ROWS = 100_000


async def parse_csv(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    reader = csv.DictReader(StringIO(text))
    chunks = []
    for row in reader:
        if len(chunks) >= MAX_CSV_ROWS:
            break
        items = [f"{k}={v}" for k, v in row.items() if v]
        if items:
            chunks.append(", ".join(items))
    return "\n".join(chunks)
