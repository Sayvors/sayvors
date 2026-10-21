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
