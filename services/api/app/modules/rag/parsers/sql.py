import re


async def parse_sql(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    pattern = r"INSERT\s+INTO\s+(\w+)\s*\((.*?)\)\s*VALUES\s*\((.*?)\)"
    matches = re.findall(pattern, text, re.IGNORECASE | re.DOTALL)
    chunks = []
    for table, columns_str, values_str in matches:
        columns = [c.strip().strip('"`[]') for c in columns_str.split(",")]
        raw_values = re.findall(r"'([^']*)'|(\w+)", values_str)
        values = [v[0] or v[1] for v in raw_values]
        if len(columns) == len(values):
            pairs = [f"{col}={val}" for col, val in zip(columns, values)]
            chunks.append(f"{table}: {', '.join(pairs)}")
        else:
            chunks.append(f"{table}: ({values_str.strip()})")
    return "\n".join(chunks) if chunks else text
