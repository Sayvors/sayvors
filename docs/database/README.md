# Sayvors — Database Architecture & Methods

Quick-reference guide for other teams. Documents how the app connects to
Postgres, how write/read splitting works, and how to flip on PgBouncer or a
read replica.

---

## 1. Two engines, two session factories

`app/database.py` creates two SQLAlchemy async engines:

| Engine | Purpose | Session factory | Dependency |
|--------|---------|----------------|------------|
| `engine` | Writes — INSERT/UPDATE/DELETE → primary | `async_session` | `get_db()` |
| `engine_read` | Reads — SELECT → replica (if configured) | `async_session_read` | `get_db_read()` |

If `DATABASE_READER_URL` is empty, `engine_read` falls back to `DATABASE_URL` —
so reads and writes hit the same database. No behavior change until you point
`DATABASE_READER_URL` at a replica.

---

## 2. Dependencies

### `get_db()` — writer session

Use for any mutating operation. Goes to the primary database.

```python
from app.database import get_db

async def create_post(db: AsyncSession = Depends(get_db)):
    ...
```

### `get_db_read()` — reader session

Use for SELECT-only operations. Goes to the replica when `DATABASE_READER_URL`
is set; otherwise hits the primary.

```python
from app.database import get_db_read

async def list_posts(db: AsyncSession = Depends(get_db_read)):
    ...
```

**Rule:** Never write inside a `get_db_read()` session. Reads are routed to a
replica that may lag the primary by milliseconds to seconds.

---

## 3. Configuration

| Env var | Default | Purpose |
|---------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@localhost:5432/sayvors` | Primary (write) connection string |
| `DATABASE_READER_URL` | `""` | Read replica connection string. Empty = reads hit primary |
| `DB_POOL_MODE` | `"session"` | `"session"` or `"transaction"` — PgBouncer pooling mode |
| `DB_POOL_SIZE` | `50` | Connection pool size per process |
| `DB_POOL_MAX_OVERFLOW` | `50` | Overflow connections beyond pool size |
| `DB_POOL_TIMEOUT_SECONDS` | `30` | Seconds to wait for a pool connection |

---

## 4. PgBouncer

PgBouncer sits between the API and Postgres, multiplexing many API connections
onto fewer Postgres connections. Prevents connection exhaustion under load.

### Dev (docker-compose.yml)

A `pgbouncer` service runs on `127.0.0.1:6432`, connecting to
`host.docker.internal:5432`. Pool mode is `transaction`.

To enable locally:
```
DATABASE_URL=postgresql+asyncpg://pgbouncer:postgres@localhost:6432/sayvors
DB_POOL_MODE=transaction
```

### Production (docker-compose.prod.yml)

`pgbouncer` service on port `6432`, env-configurable Postgres host:
```
PGBOUNCER_PASSWORD=${PGBOUNCER_PASSWORD}
PGBOUNCER_POSTGRES_HOST=${PGBOUNCER_POSTGRES_HOST}
PGBOUNCER_POOL_MODE=transaction
PGBOUNCER_DEFAULT_POOL_SIZE=100
PGBOUNCER_MAX_CLIENT_CONN=400
```

Set `DATABASE_URL` in `.env.prod` to point at PgBouncer instead of Postgres
directly.

---

## 5. Read replica

When you provision a read-only Postgres replica:

1. Set `DATABASE_READER_URL=postgresql+asyncpg://replica-user:pass@replica-host:5432/sayvors`
2. Route read endpoints to `get_db_read()`
3. Keep write endpoints on `get_db()`

Example route split:

```python
# Write — goes to primary
@router.post("/posts")
async def create_post(db: AsyncSession = Depends(get_db)):
    ...

# Read — goes to replica (or primary if no replica configured)
@router.get("/posts")
async def list_posts(db: AsyncSession = Depends(get_db_read)):
    ...
```

**Important:** Replica lag means a write followed immediately by a read may
not see the just-written row. Use `get_db()` for read-after-write consistency.

---

## 6. Files touched

| File | What changed |
|------|-------------|
| `app/database.py` | Split into `engine`/`async_session` (write) + `engine_read`/`async_session_read` (read); added `get_db_read()` |
| `app/config.py` | Added `DATABASE_READER_URL`, `DB_POOL_MODE` |
| `docker-compose.yml` | Added `pgbouncer` service (dev) |
| `docker-compose.prod.yml` | Added `pgbouncer` service (staging) |
| `docs/tracking/production-checklist.md` | Added I-5, I-7 infrastructure checks + env var reference |
| `docs/tracking/production-later.md` | Added PgBouncer + reader URL rows to Postgres table |

---

## 7. Checklist before flipping to replica

- [ ] `DATABASE_READER_URL` points to a read-only replica
- [ ] Read endpoints use `get_db_read()`, write endpoints use `get_db()`
- [ ] No write operations inside `get_db_read()` sessions
- [ ] Team understands replica lag implications for read-after-write
- [ ] PgBouncer `pool_mode=transaction` matches `DB_POOL_MODE=transaction`
- [ ] `DB_POOL_SIZE` right-sized per process (5–50 depending on instance size)

---

## 8. Anti-patterns

| Don't | Do |
|-------|----|
| Use `get_db_read()` for INSERT/UPDATE/DELETE | Use `get_db()` for all writes |
| Assume replica is in sync with primary | Account for replica lag; use `get_db()` if you need the latest write |
| Mix read and write in the same `get_db_read()` session | Keep sessions single-purpose |
| Set `DB_POOL_MODE=session` with PgBouncer transaction mode | Match `DB_POOL_MODE` to PgBouncer's configured pool mode |
