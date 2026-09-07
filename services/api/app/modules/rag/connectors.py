"""Live database connectors for databanks (PostgreSQL / MySQL).

Read-only by design:
- Only SELECT / WITH statements are accepted (single statement, no stacking).
- Every query gets a forced LIMIT, a row cap, and a hard timeout.
- Connection credentials live encrypted in databank_sources; only an
  in-memory DbConfig ever touches a driver. Passwords are never logged.
"""

import asyncio
import csv
import io
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 8
QUERY_TIMEOUT = 15
DEFAULT_PREVIEW_LIMIT = 20
DEFAULT_QUERY_LIMIT = 200
MAX_QUERY_LIMIT = 1000
MAX_INGEST_ROWS = 1000


@dataclass
class DbConfig:
    db_type: str  # "postgres" | "mysql"
    host: str = "localhost"
    port: int = 5432
    database: str = ""
    username: str = ""
    password: str = ""


def default_port(db_type: str) -> int:
    return 5432 if db_type == "postgres" else 3306


def _redacted(cfg: DbConfig) -> str:
    return f"{cfg.db_type}://{cfg.username}@{cfg.host}:{cfg.port}/{cfg.database}"


# ── guards ────────────────────────────────────────────────

_WS_OR_COMMENT = re.compile(r"^\s*(--[^\n]*|/\*.*?\*/|\()", re.DOTALL)


def _strip_leading_comments(sql: str) -> str:
    text = sql.strip()
    while True:
        m = _WS_OR_COMMENT.match(text)
        if not m:
            return text
        text = text[m.end():].lstrip()
        if not text:
            return text


def validate_readonly_sql(sql: str, limit: int) -> str:
    """Return a safe, limited single SELECT/WITH statement or raise ValueError."""
    text = _strip_leading_comments(sql or "")
    text = text.rstrip().rstrip(";").strip()
    if not text:
        raise ValueError("Query is empty")
    if ";" in text:
        raise ValueError("Only a single statement is allowed")
    first_word = text.split(None, 1)[0].upper() if text.split() else ""
    if first_word not in ("SELECT", "WITH"):
        raise ValueError("Only SELECT / WITH queries are allowed")
    if not re.search(r"\bLIMIT\b", text, re.IGNORECASE):
        text = f"{text} LIMIT {limit}"
    return text


# ── drivers ───────────────────────────────────────────────

async def _pg_fetch(cfg: DbConfig, sql: str, args: tuple = ()) -> tuple[list[str], list[tuple]]:
    import asyncpg

    conn = await asyncio.wait_for(
        asyncpg.connect(
            host=cfg.host,
            port=cfg.port,
            database=cfg.database,
            user=cfg.username,
            password=cfg.password or None,
            timeout=CONNECT_TIMEOUT,
        ),
        timeout=CONNECT_TIMEOUT + 2,
    )
    try:
        rows = await asyncio.wait_for(
            conn.fetch(sql, *args), timeout=QUERY_TIMEOUT
        )
        columns = list(rows[0].keys()) if rows else []
        return columns, [tuple(r.values()) for r in rows]
    finally:
        await conn.close()


async def _mysql_fetch(cfg: DbConfig, sql: str, args: tuple = ()) -> tuple[list[str], list[tuple]]:
    import aiomysql

    conn = await asyncio.wait_for(
        aiomysql.connect(
            host=cfg.host,
            port=cfg.port,
            db=cfg.database,
            user=cfg.username,
            password=cfg.password or "",
            connect_timeout=CONNECT_TIMEOUT,
        ),
        timeout=CONNECT_TIMEOUT + 2,
    )
    try:
        async with conn.cursor() as cur:
            await asyncio.wait_for(
                cur.execute(sql, args or None), timeout=QUERY_TIMEOUT
            )
            rows = await cur.fetchall()
            columns = [d[0] for d in (cur.description or [])]
            return columns, [tuple(r) for r in rows]
    finally:
        conn.close()


async def _fetch(cfg: DbConfig, sql: str, args: tuple = ()) -> tuple[list[str], list[tuple]]:
    if cfg.db_type == "postgres":
        return await _pg_fetch(cfg, sql, args)
    if cfg.db_type == "mysql":
        return await _mysql_fetch(cfg, sql, args)
    raise ValueError(f"Unsupported database type: {cfg.db_type}")


def _ver_sql(cfg: DbConfig) -> str:
    return "SELECT version()" if cfg.db_type == "postgres" else "SELECT VERSION()"


# ── public API ────────────────────────────────────────────

async def test_connection(cfg: DbConfig) -> dict:
    """Connect + run a trivial query. Returns {ok, version} or raises."""
    try:
        _columns, rows = await _fetch(cfg, _ver_sql(cfg))
    except Exception as e:
        logger.warning("DB connection test failed for %s: %s", _redacted(cfg), e)
        raise ValueError(f"Could not connect: {e}") from e
    version = str(rows[0][0]) if rows else "unknown"
    return {"ok": True, "version": version[:200]}


async def list_tables(cfg: DbConfig) -> list[dict]:
    """Return [{name, columns}] for user tables."""
    if cfg.db_type == "postgres":
        sql = """
            SELECT t.table_name,
                   (SELECT count(*) FROM information_schema.columns c
                     WHERE c.table_schema = 'public' AND c.table_name = t.table_name) AS col_count
            FROM information_schema.tables t
            WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
            ORDER BY t.table_name
        """
        _cols, rows = await _fetch(cfg, sql)
        return [{"name": r[0], "columns": int(r[1])} for r in rows]
    sql = """
        SELECT table_name,
               (SELECT count(*) FROM information_schema.columns c
                 WHERE c.table_schema = DATABASE() AND c.table_name = t.table_name) AS col_count
        FROM information_schema.tables t
        WHERE t.table_schema = DATABASE() AND t.table_type = 'BASE TABLE'
        ORDER BY t.table_name
    """
    _cols, rows = await _fetch(cfg, sql)
    return [{"name": r[0], "columns": int(r[1])} for r in rows]


async def preview_table(cfg: DbConfig, table: str, limit: int = DEFAULT_PREVIEW_LIMIT) -> dict:
    """Column names + first N rows of one table."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table or ""):
        raise ValueError("Invalid table name")
    limit = max(1, min(limit, 100))
    if cfg.db_type == "postgres":
        columns, rows = await _fetch(
            cfg, f'SELECT * FROM "{table}" LIMIT {limit + 1}'
        )
    else:
        columns, rows = await _fetch(
            cfg, f"SELECT * FROM `{table}` LIMIT {limit + 1}"
        )
    truncated = len(rows) > limit
    return {
        "table": table,
        "columns": columns,
        "rows": [[_safe_cell(v) for v in r] for r in rows[:limit]],
        "truncated": truncated,
    }


async def run_query(cfg: DbConfig, sql: str, limit: int = DEFAULT_QUERY_LIMIT) -> dict:
    """Run a guarded read-only query. Returns {columns, rows, truncated}."""
    limit = max(1, min(limit, MAX_QUERY_LIMIT))
    safe_sql = validate_readonly_sql(sql, limit)
    try:
        columns, rows = await _fetch(cfg, safe_sql)
    except ValueError:
        raise
    except Exception as e:
        logger.warning("DB query failed for %s: %s", _redacted(cfg), e)
        raise ValueError(f"Query failed: {e}") from e
    return {
        "columns": columns,
        "rows": [[_safe_cell(v) for v in r] for r in rows[:limit]],
        "row_count": len(rows),
        "truncated": len(rows) > limit,
    }


def _safe_cell(value) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def rows_to_csv(columns: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if v is None else v for v in row])
    return buf.getvalue()
