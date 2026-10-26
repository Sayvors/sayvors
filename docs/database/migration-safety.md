# Migration Chain and Deploy Safety

How the alembic migration chain is validated, and the checklist that must pass
before anything is pushed to `staging`.

This document describes the mechanism as it is implemented. It is not a record
of a past incident.

---

## 1. Why this exists

The api container runs `alembic upgrade head` on boot (see
`services/api/Dockerfile`). That single command is the gate between "the
image started" and "the schema is correct". When the chain is malformed,
alembic refuses to run at all and the container crash-loops:

```
FAILED: Multiple head revisions are present for given argument 'head'
```

Two failure modes are invisible until that point:

| Failure | What the container does | What the user sees |
|---|---|---|
| Forked chain (2+ heads) | `alembic upgrade head` refuses to run | Container crash-loops on boot |
| Duplicate revision id | Alembic keeps one file silently, graph is wrong | Same, plus a `UserWarning` in the log |
| Model column with no migration | Container boots fine, then the query 500s | `column X does not exist` on first use |

The third is the nastiest: the deploy looks successful, and the failure
surfaces later as an application error on a code path nobody touched.

---

## 2. The chain rules

### One head, always

A migration's `down_revision` must be the **current head** at the moment the
file is written - not an already-used parent. Pointing two migrations at the
same parent creates a fork.

```python
# WRONG - both point at 7a8b9c0d1e2f, creating two branches
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = '7a8b9c0d1e2f'

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = '7a8b9c0d1e2f'   # <-- fork
```

The correct chain is linear:

```
7a8b9c0d1e2f -> b1c2d3e4f5a6 -> c1d2e3f4a5b6 -> d2e3f4a5b6c7 (head)
```

When two genuine branches exist, create an explicit **merge revision** rather
than leaving two heads:

```python
revision: str = 'c69270b5cb92'
down_revision: Union[str, Sequence[str], None] = (
    '20261015090000',
    'z3a4b5c6d7e8',
)
```

### Revision ids are unique

The revision id is the primary key of alembic's revision map. Two files
claiming the same id means one silently overwrites the other, and the loaded
graph is not what anyone intended.

Revision ids must also be **globally unique across branches**, not just within
one. A hotfix pushed straight to `staging` that reuses an id already used on
`development` collides the moment the two branches merge.

To fix a collision, rename the id in one of the files. If the migration has
already run on a database, that database's `alembic_version` holds the old
id, so the rename needs a matching `alembic stamp`.

### Migrations are re-runnable

`op.add_column` and `op.create_index` have no `IF NOT EXISTS` form. Against a
database that was patched by hand - or a partially-applied migration - they
raise `DuplicateColumn` / `DuplicateTable` and abort the boot.

Prefer raw SQL with the guard:

```python
op.execute(
    "ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS contact_phone_hash varchar(64)"
)
op.execute(
    "CREATE INDEX IF NOT EXISTS ix_channel_messages_inbox "
    "ON channel_messages (channel_id, contact_phone_hash, created_at)"
)
```

### Enum types are created once

```python
job_type_enum = sa.Enum(..., name="job_type", create_type=False)
job_type_enum.create(op.get_bind(), checkfirst=True)
```

`create_type=False` on the column plus an explicit `checkfirst=True` create
means the type is never created twice.

### Model and migration move together

A column on an ORM model that no migration creates is the "column X does not
exist" outage. Every model column must be traceable to a migration.

The reverse direction — a migration object the model does not describe — is
covered by §10: a database rebuilt from `Base.metadata` alone must match the
migrated one.

---

## 3. The guards

Two callers share one implementation, so the local check and the CI check can
never drift apart.

### `services/api/migration_guard.py`

The analysis module. Exposes `analyze_chain()` and `find_model_drift()`, plus
`format_report()` for human-readable output.

The guard is hermetic. It reads migration files and ORM metadata only: it never
opens a database connection and never uses application configuration. During
the model import it seeds a throwaway `JWT_SECRET` and restores the previous
value afterwards, because `app/config.py` fails closed at import time while the
secret is still the placeholder. That is why CI can run it as a plain step with
no repository secret — a guard that needs deploy secrets cannot gate a deploy.

It checks:

- **duplicate revision ids** - two files claiming one id
- **multiple heads** - a forked chain
- **orphan down_revisions** - a parent that does not exist
- **unreachable revisions** - no path from a base reaches them
- **migration cycles** - `alembic upgrade` would recurse forever
- **model drift** - model columns that no migration creates

### `services/api/tests/test_migration_heads.py`

The pytest gate. Runs the guard, and - importantly - asserts that the guard
*would* catch each failure mode it exists to catch, by writing deliberately
broken migrations into a temporary directory. A guard that cannot fail is
worse than no guard, because it gives false confidence.

### `scripts/pre_push_check.py`

The local checklist. Run before every push:

```bash
python scripts/pre_push_check.py
```

---

## 4. The pre-push checklist

```
python scripts/pre_push_check.py
```

| # | Check | Fails when |
|---|-------|-----------|
| 1 | Migration chain integrity | duplicate ids, multiple heads, orphans, cycles, unreachable revisions |
| 2 | Model / migration parity | a model column that no migration creates |
| 3 | Migration <-> model coupling | a schema change with no model change (warn) |
| 4 | Alembic loads a single head | alembic's own loader disagrees with the guard |
| 5 | New migrations are re-runnable | a new migration uses `op.add_column` / `op.create_index` without `IF NOT EXISTS` (warn) |
| 6 | Migration guard tests | the guard tests fail |
| 7 | Branch vs origin/staging | pushing to staging would ship a build missing staging-only commits |
| 8 | No secrets in the working tree | an obvious credential pattern in a changed file |

Exit code `0` means everything passed. Non-zero means **do not push**.

Checks 1, 2 and 4 are the ones that would have caught the staging
crash-loop. Check 2 is the one that catches the model drift.

### Making it automatic

```bash
git config core.hooksPath .githooks
```

`.githooks/pre-push` runs the checklist and blocks the push on failure.

---

## 5. CI enforcement

`.github/workflows/ci.yml` runs on every push to `staging` and fails the
build on a forked chain:

```yaml
- name: Verify single alembic head
  working-directory: services/api
  run: |
    set -e
    HEADS=$(alembic heads | wc -l)
    if [ "$HEADS" -ne 1 ]; then
      echo "FATAL: alembic has $HEADS heads - the migration chain forked."
      alembic heads
      exit 1
    fi
```

The `test-backend` job also runs `tests/test_migration_heads.py`, which
covers duplicate ids, orphans and model drift.

The `Deploy staging` workflow's `ci-gate` job waits for both CI jobs to be
green before building an image, so a broken chain never reaches a container.

---

## 6. Branch rules

`development` is the source of truth. `staging` is what deploys.

**Do not push fixes straight to `staging`.** A direct push cannot be cleaned
up by a later merge: git only brings files *into* the target branch, so a
file that exists only on `staging` survives every subsequent merge from
`development`. That is how a duplicate revision id survived a merge and kept
the deploy broken.

If a hotfix must go out immediately, push it to a branch cut from `staging`,
merge it into `staging`, and back-merge `staging` into `development`.

---

## 7. GHCR package visibility

The repository being public does **not** make the container package public.
Package visibility is a separate setting, and a package created while the
repository was private stays private.

A private package returns `401 UNAUTHORIZED` on the anonymous token exchange:

```bash
curl -s "https://ghcr.io/token?scope=repository:sayvors/sayvors-api:pull&service=ghcr.io"
# {"errors":[{"code":"UNAUTHORIZED","message":"authentication required"}]}
```

which surfaces on the deploy host as:

```
Head "https://ghcr.io/v2/sayvors/sayvors-api/manifests/staging": denied: denied
```

`Deploy staging` does **not** change package visibility: it builds and pushes
`:staging`, and logs in with `GITHUB_TOKEN` for the push only. Nothing in the
workflow makes the package public. If the package is private, either make it
public once (Packages -> sayvors-api -> Package settings -> Change visibility)
or give the deploy host a credential that carries `read:packages`.

The image contains no secrets - all runtime configuration comes from
`.env.prod` via compose `env_file` - so publishing it publicly is safe.

### Stale credentials on the deploy host

A revoked PAT left in `~/.docker/config.json` breaks pulls even for a public
package: docker sends the dead `Authorization` header and GHCR rejects it.

```bash
docker logout ghcr.io
```

Then verify:

```bash
docker pull ghcr.io/sayvors/sayvors-api:staging
```

---

## 8. Deploy sequence

The deploy is manual on the host. `Deploy staging` builds and pushes the
image; a human pulls it up. The `:staging` tag only moves after CI passes on
`staging`, so pulling before that point silently redeploys the previous image.

```bash
cd ~/sayvors
git rev-parse --abbrev-ref HEAD             # must print: staging
git pull --ff-only origin staging
rm -f docker-compose.override.yml          # it overrides the api command and skips migrations
docker compose -f docker-compose.prod.yml pull api worker
docker compose -f docker-compose.prod.yml up -d --remove-orphans
docker compose -f docker-compose.prod.yml logs --tail=40 api
```

`--no-deps` is deliberately absent: `api` depends on `redis` and `kafka` with
`condition: service_healthy`, so skipping dependencies leaves the API pointing
at containers that may not be running. `up -d` recreates a service when its
image digest changed, which is what a fresh `:staging` push produces.

Verify:

```bash
docker compose -f docker-compose.prod.yml exec api alembic current   # expect the single head
docker compose -f docker-compose.prod.yml ps
curl -fsS https://api.staging.sayvors.com/readyz
```

Containers have no `container_name` in `docker-compose.prod.yml`, so they are
named `<project>-<service>-1` (for example `sayvors-api-1`) and the name
changes with the directory. Always address them through `docker compose`
rather than `docker logs sayvors-api` / `docker exec sayvors-api`.

`docker-compose.override.yml` must not exist on the host. It replaces the
api container's command with a bare `uvicorn`, which skips the
`alembic upgrade head` step entirely - the container comes up against an
un-migrated schema.

---

## 9. The pgvector requirement

Migration `c3d4e5f6a7b8` adds `document_chunks.embedding_vector vector(1024)`
and the HNSW / GIN indexes that make databank search scale. The vector
column needs the `vector` extension, so the migration has two branches,
chosen by `EMBEDDINGS_ENABLED` (see `Settings.embeddings_enabled`):

* **on** (the default outside development/test) — creates the extension,
  converts any TEXT placeholder left by an earlier run, adds
  `embedding_vector vector(1024)` and both indexes. If the extension cannot
  be created the deploy **fails loudly**: a database without pgvector cannot
  hold a vector column, and silently continuing would leave the app writing
  to a schema it cannot search.
* **off** (the default everywhere else) — creates `embedding_vector` as
  `TEXT` so the ORM still maps `document_chunks`, builds the GIN keyword
  index, and continues. Databank search is keyword-only until embeddings are
  turned on; the API reports that as `degraded`.

The switch matters beyond this migration: `hybrid_search` skips the pgvector
operators, ingest writes no vectors, and the query path never calls an
embedding provider while it is off. Nothing fails, results are just keyword
based.

| Environment | Requirement | How to check |
|---|---|---|
| CI | postgres service runs the `pgvector/pgvector:pg15` image (plain `postgres:15-alpine` has no extension files) | `tests/test_rag_pgvector.py` runs there and skips everywhere else |
| Staging / production (AWS RDS) | a PostgreSQL version that supports pgvector, and a role allowed to `CREATE EXTENSION vector` | `SELECT * FROM pg_available_extensions WHERE name = 'vector';` then `CREATE EXTENSION IF NOT EXISTS vector;` |
| Local development | only when embeddings are turned on; the default local setup needs no extension at all | `SELECT * FROM pg_available_extensions WHERE name = 'vector';` when `EMBEDDINGS_ENABLED=true` |

Check before deploying:

```bash
# 1. is the extension installable at all?
psql "$DATABASE_URL" -c "SELECT default_version FROM pg_available_extensions WHERE name = 'vector';"

# 2. does this role have the right to create it?
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 3. after the deploy, the column and the indexes must exist
psql "$DATABASE_URL" -c "\d document_chunks" | grep embedding_vector
psql "$DATABASE_URL" -c "SELECT indexname FROM pg_indexes WHERE tablename = 'document_chunks';"
```

### Installing pgvector on a local Windows PostgreSQL

The local development database is a Windows PostgreSQL install, which does not ship
pgvector. The extension has to be added once:

1. Download the `windows-x64` build of the latest pgvector release
   (<https://github.com/pgvector/pgvector/releases>).
2. Copy `vector.control` into the server's extension folder:
   `C:\Program Files\PostgreSQL\18\share\extension\`
3. Copy the `vector--*.dll` files into the server's library folder:
   `C:\Program Files\PostgreSQL\18\lib\`
4. Restart the PostgreSQL service:
   `Restart-Service postgresql-x64-18`
5. Enable it and migrate:

```bash
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
cd services/api
alembic upgrade head
```

Until the extension is installed, leave `EMBEDDINGS_ENABLED` unset (or
`false`): the migration creates the TEXT placeholder, `alembic upgrade head`
reaches the current head, and workers stop failing on the columns that come
after it (`dedupe_key`, `hard_deadline_at`, `job_lane_heartbeats`). Search is
keyword-only in that mode.

### Turning embeddings on later

If the database already ran `c3d4e5f6a7b8` with embeddings off, it holds a
TEXT placeholder and the revision is already stamped, so flipping the flag
does not re-run the migration by itself. With pgvector installed:

```bash
# Downgrade drops the empty placeholder (all values are NULL - no chunk loses
# a vector, because none were written while embeddings were off).
cd services/api
alembic downgrade -1
EMBEDDINGS_ENABLED=true alembic upgrade head
```

Production must never need this: it defaults to enabled, so the first deploy
creates the real column.

If `CREATE EXTENSION` is refused **while embeddings are enabled**, the
database is not ready for this migration: enable pgvector on the instance
(RDS: the engine version has to support it) and re-run as a role with the
right to create extensions - or set `EMBEDDINGS_ENABLED=false` to run
keyword-only. The api container logs `pgvector codec not registered` once
either way; in the disabled case that is expected and does not affect
keyword search.

Existing chunks have no vector after the migration. Backfill them with:

```bash
cd services/api
python scripts/backfill_embeddings.py             # dry-run report
python scripts/backfill_embeddings.py --apply     # writes the vectors
```

The script is re-runnable and only touches chunks whose vector is still
NULL (unless `--force` is passed).

---

## 10. Models are the schema source of truth

The Alembic chain is the deployment mechanism; `Base.metadata` is the schema
definition. A database rebuilt with `create_all` alone — no migration files —
must be indistinguishable from one built by `alembic upgrade head`.

### What the rebuild covers

| Area | Mechanism |
|---|---|
| Tables | every module's models are imported by `alembic/env.py`; `review_engine/models.py` also imports `csv_models`, so `csv_uploads` / `csv_rows` are never missing |
| Unique + composite indexes | declared in `__table_args__` with the migration's exact names (`ix_review_issues_handoff_code`, `ix_review_issues_tenant_ticket`, `uq_channel_threads_channel_contact`, ...) |
| Partial unique indexes | `postgresql_where` on the `Index` (`uq_billing_events_tenant_idempotency`, `uq_channel_comments_platform_id`) |
| GIN / HNSW / expression / partial DDL | `app/db_indexes.py` — `register_postgres_index_ddl()` attaches an `after_create` hook that runs only on PostgreSQL and is a no-op on SQLite. The hook registers the index names, and `alembic/env.py` filters them out of autogenerate, so a routine `alembic revision --autogenerate` never proposes dropping them |
| pgvector | `EmbeddingVector` emits `VECTOR(1024)` when embeddings are enabled and `TEXT` otherwise, matching migration `c3d4e5f6a7b8`; `database.py` creates the extension in a `before_create` hook |
| CSV payload | `csv_rows.data` is `JSONB` on PostgreSQL (`@>` and `jsonb_each_text()` need it) and JSON on SQLite |
| Catalog data | `review_engine/catalog_seed.py` runs on startup: `INSERT ... ON CONFLICT DO NOTHING` for tones (4), dialects (23), response strategies (10), voice models (2). Admin edits survive; a deleted row is refilled on the next start |

The PostgreSQL-only hooks are the reason the SQLite test suite still works:
the dialect guard skips them there, while the fresh-rebuild probe (below)
verifies they exist on PostgreSQL.

### The one deliberate difference: server defaults

The migrated database carries server defaults (`now()`, `0`, `false`, enum
labels) on the order of 180 columns. The models do not repeat them, because
every one of those columns already has a Python-side default (`default=` /
`default_factory`): an ORM insert always supplies the value, and the server
default only matters to raw SQL outside the ORM. Duplicating ~180 literals in
the models would add no behavioural change.

Two columns had a server default and no Python default.
`user_feedback.emoji_rating` keeps it (`server_default="3"` on the model).
`auto_reply_configs.model` carried the original `'openai:gpt-4o-mini'`
default, which contradicted the documented design — NULL means "resolve the
tenant default from the admin-managed enabled models". The parity migration
drops that default instead of teaching the model to reproduce it, so a new
row that omits the column really is NULL.

### Verification

```bash
cd services/api
python -m pytest tests/test_model_schema.py tests/test_catalog_seed.py
python -m alembic check
```

`test_model_schema.py` pins the declarations that used to drift; it does not
need a live PostgreSQL. `alembic check` compares the models against a migrated
database and must report `No new upgrade operations detected.` — the five
PostgreSQL-only hook indexes are filtered out of the comparison because they
exist in the database but not in `Base.metadata`.

The stronger check is a throwaway PostgreSQL database
built with `Base.metadata.create_all` and compared against a migrated one:
same 72 tables, same index names, same foreign keys and delete rules, same
types, and the changed columns (`csv_rows.data`, `document_chunks.
embedding_vector`, `whatsapp_thread_states.contact_phone`) carrying the same
nullability.
