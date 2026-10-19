# Sayvors — Agent Working Rules

Root-level rules for any agent working in this repo. These override default habits.

---

## 1. Test only what you changed

**Never run the full suite to validate a scoped change.** The suite takes ~20 minutes
and burns CI minutes on GitHub for nothing.

Instead:

1. Identify the test files that cover the code you touched.
2. Run **only those files**:
   ```bash
   cd services/api
   python -m pytest tests/test_foo.py tests/test_bar.py -q
   ```
3. Run the broader suite **only** when the change is cross-cutting (shared model,
   migration, config, auth, database engine) or before a release/deploy gate.

Touching a model, a migration, `config.py`, `database.py`, or anything under
`app/core/` means run the suite. A change inside one module does not.

---

## 2. Code must be production-ready

Not "works on my machine". Production-ready means:

- **No silent failure.** Errors propagate or are logged with enough context to
  diagnose. Never swallow an exception to make a test pass.
- **No placeholder logic.** No `TODO`, no `pass  # later`, no stubbed branches
  left in shipped paths.
- **Real database, real concurrency.** Assume multiple workers run at once —
  claims must be atomic, commits must be ordered, no read-modify-write races.
- **Idempotent where it matters.** Migrations must be re-runnable (`IF NOT EXISTS`),
  cleanup jobs must be safe to run twice, retries must not double-apply.
- **Bounded resources.** Every loop, queue, and query has a limit. No unbounded
  growth, no N+1 that will bite at 1000 tenants.
- **Fail closed on security paths.** Auth, SSRF guards, and budget gates deny
  rather than degrade. Fail-open only where the docstring justifies it.
- **No magic numbers.** Constants with a name and a reason.
- **Type hints and docstrings** on anything non-obvious, explaining *why*, not *what*.
- **Comments explain reasoning, not narration.** If the code says what it does,
  the comment should say why it does it that way.

---

## 3. Migrations and models move together

A model column change **requires** an alembic migration in the same change. The
staging deploy failed repeatedly because a column existed in the model with no
migration — the container booted, then crashed on the first query that touched it.

Rules:
- One migration per logical change, named `<rev>_<what_it_does>.py`.
- `down_revision` must point at the current head. Check for a duplicate
  revision ID before committing — alembic silently allows two files with the
  same revision and then reports "Multiple head revisions are present".
- Migrations must be idempotent where the target DB may already have the
  object (`CREATE INDEX IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`).
- Enum creation needs `create_type=False` on the column plus an explicit
  `.create(checkfirst=True)`, so the type is never created twice.

---

## 4. Never push unless asked

Commit freely. **Push only when the user explicitly says push.** An unpushed
branch is easy to fix; a pushed branch is a deployed artifact.

The user merges `development` → `staging` via PR and runs the deploy themselves.

---

## 5. Before saying "done", verify

- The specific test files you touched pass, locally, with the real output shown.
- `npx tsc --noEmit` passes for any frontend change.
- `npm run build` passes for any frontend change.
- The git diff contains only what you intended to change.
- Nothing uncommitted is left behind accidentally.

---

## 6. Security documentation lives in `docs/security/`

`docs/security/` holds the durable "how this is implemented" documents:
how a guard works, what it protects, what the invariants are.

`docs/tracking/` holds status and progress notes.

Both are valid homes for the same subject, but a permanent implementation
decision belongs in `docs/security/`. Do not write "we fixed X" — write how X
is implemented now, so the document stays true when the method changes.

---

## 7. Read the readiness report before starting work

`readiness-report.html` is the consolidated audit of what is broken and what is
fixed, with per-item status. Check it before picking up an item so you do not
re-do finished work, and update it when you finish something.
