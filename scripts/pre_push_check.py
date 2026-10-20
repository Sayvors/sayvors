#!/usr/bin/env python3
"""Pre-push checklist for the Sayvors repo.

Run this BEFORE every push. It exists because the staging deploy failed
repeatedly on things that were invisible until the container crash-looped on
boot:

  - a forked migration chain (multiple heads) -> `alembic upgrade head`
    refuses to run
  - two migration files claiming the same revision id -> alembic silently
    keeps one and the graph is not what anyone intended
  - a model column with no migration creating it -> the container boots fine,
    then the first request touching that column 500s
  - a model change with no migration at all -> same, but worse, because the
    column is missing entirely
  - a migration that was never applied to the target database

Usage:

    python scripts/pre_push_check.py                 # checks for this branch
    python scripts/pre_push_check.py --branch staging
    python scripts/pre_push_check.py --against origin/staging
    python scripts/pre_push_check.py --skip-db       # no database checks

Exit code 0 means everything passed. Non-zero means DO NOT PUSH.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "services" / "api"

# ANSI-free output: this runs in CI logs and in a pre-push hook.
PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

_results: list[tuple[str, str, str, list[str]]] = []


def record(status: str, name: str, detail: str = "", notes: list[str] | None = None) -> None:
    _results.append((status, name, detail, notes or []))


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a command, returning (exit_code, stdout, stderr)."""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return proc.returncode, proc.stdout, proc.stderr


def section(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_migration_chain() -> None:
    """Single head, no duplicate revision ids, no orphans, no cycles."""
    section("1. Migration chain integrity")
    sys.path.insert(0, str(API_DIR))
    try:
        import migration_guard as guard
    except Exception as exc:  # pragma: no cover - import guard
        record(FAIL, "migration chain", f"could not import guard: {exc}")
        return

    report = guard.analyze_chain()
    detail = (
        f"{len(report.migrations)} migrations, "
        f"{len(report.roots)} root(s), "
        f"{len(report.heads)} head(s): {', '.join(report.heads)}"
    )

    if report.problems:
        record(FAIL, "migration chain", detail, report.problems)
        for problem in report.problems:
            print(f"    - {problem}")
        return

    record(PASS, "migration chain", detail)
    print(f"    {detail}")


def check_model_drift() -> None:
    """Every model column must be created by some migration."""
    section("2. Model / migration parity")
    sys.path.insert(0, str(API_DIR))
    try:
        import migration_guard as guard
    except Exception as exc:  # pragma: no cover - import guard
        record(FAIL, "model parity", f"could not import guard: {exc}")
        return

    drift = guard.find_model_drift()
    if drift:
        record(
            FAIL,
            "model parity",
            f"{len(drift)} model column(s) with no migration",
            [
                f"{item} - add a migration that creates it, "
                f"or remove it from the model"
                for item in drift
            ],
        )
        for item in drift:
            print(f"    - {item}")
        return

    record(PASS, "model parity", "every model column is created by a migration")
    print("    every model column is created by a migration")


def check_migration_files_changed() -> None:
    """If migrations changed, the chain check above already covers them.

    This check exists to make the coupling explicit in the output: a push that
    touches a migration MUST also touch a model (or be a no-op schema change).
    """
    section("3. Migration <-> model coupling (changed files)")
    code, stdout, _ = run(
        ["git", "diff", "--name-only", "HEAD"], cwd=REPO_ROOT
    )
    if code != 0:
        record(WARN, "migration coupling", "could not read git diff")
        return

    changed = [line for line in stdout.splitlines() if line.strip()]
    migrations_changed = [
        c for c in changed if "/alembic/versions/" in c.replace("\\", "/")
    ]
    models_changed = [
        c
        for c in changed
        if "/models.py" in c.replace("\\", "/")
        or c.replace("\\", "/").endswith("/models.py")
    ]

    if migrations_changed and not models_changed:
        record(
            WARN,
            "migration coupling",
            f"{len(migrations_changed)} migration file(s) changed, no model file changed",
            [
                "A schema change usually implies a model change. If this "
                "migration only alters an existing column, ignore this warning."
            ],
        )
        print(
            f"    {len(migrations_changed)} migration file(s) changed, "
            f"no model file changed (review this)"
        )
        return

    record(
        PASS,
        "migration coupling",
        f"{len(migrations_changed)} migration(s), {len(models_changed)} model file(s) changed",
    )
    print(
        f"    {len(migrations_changed)} migration(s), "
        f"{len(models_changed)} model file(s) changed"
    )


def check_alembic_current() -> None:
    """The chain must be at exactly one head when alembic loads it."""
    section("4. Alembic loads a single head")
    code, stdout, stderr = run(
        [sys.executable, "-m", "alembic", "heads"], cwd=API_DIR
    )
    output = (stdout + stderr).strip()

    if code != 0:
        record(FAIL, "alembic heads", "alembic heads failed", [output[-800:]])
        print(f"    {output[-400:]}")
        return

    if "present more than once" in output:
        record(
            FAIL,
            "alembic heads",
            "duplicate revision id detected by alembic",
            [
                line
                for line in output.splitlines()
                if "present more than once" in line
            ],
        )
        for line in output.splitlines():
            if "present more than once" in line:
                print(f"    {line}")
        return

    heads = [line.strip() for line in stdout.splitlines() if line.strip()]
    if len(heads) != 1:
        record(
            FAIL,
            "alembic heads",
            f"{len(heads)} heads reported",
            heads,
        )
        for head in heads:
            print(f"    {head}")
        return

    record(PASS, "alembic heads", heads[0])
    print(f"    {heads[0]}")


def check_migrations_are_idempotent() -> None:
    """New migrations that may run against an already-migrated DB need IF NOT EXISTS.

    ``op.add_column`` and ``op.create_index`` have no ``IF NOT EXISTS`` form,
    so a migration using them crashes if the object already exists. That is
    fine for a virgin database and fatal for a database that was patched by
    hand - which is exactly what happened on staging.

    Only migrations added or changed in this branch are checked. Historical
    migrations are immutable: rewriting them does not change what a database
    that already ran them contains, and flagging them produces a wall of
    noise that trains people to ignore the check.
    """
    section("5. New migrations are re-runnable")
    sys.path.insert(0, str(API_DIR))
    try:
        import migration_guard as guard
    except Exception as exc:  # pragma: no cover - import guard
        record(WARN, "idempotent migrations", f"could not import guard: {exc}")
        return

    changed = _changed_migration_files()
    if not changed:
        record(PASS, "idempotent migrations", "no migrations changed in this branch")
        print("    no migrations changed in this branch")
        return

    risky: list[str] = []
    for path in changed:
        src = path.read_text(encoding="utf-8")
        if "op.add_column(" in src and "IF NOT EXISTS" not in src.upper():
            risky.append(f"{path.name}: op.add_column without IF NOT EXISTS")
        if "op.create_index(" in src and "IF NOT EXISTS" not in src.upper():
            risky.append(f"{path.name}: op.create_index without IF NOT EXISTS")

    if risky:
        record(
            WARN,
            "idempotent migrations",
            f"{len(risky)} new migration(s) are not re-runnable",
            risky,
        )
        for item in risky:
            print(f"    - {item}")
        return

    record(
        PASS,
        "idempotent migrations",
        f"{len(changed)} new migration(s), all use IF NOT EXISTS",
    )
    print(f"    {len(changed)} new migration(s), all use IF NOT EXISTS")


def _changed_migration_files() -> list[Path]:
    """Migration files added or modified relative to the merge base.

    Uses the merge base rather than HEAD~1 so that a multi-commit branch is
    judged as a whole.
    """
    code, base_out, _ = run(
        ["git", "merge-base", "HEAD", "origin/staging"], cwd=REPO_ROOT
    )
    base = base_out.strip() if code == 0 else ""
    if not base:
        code, base_out, _ = run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT)
        base = base_out.strip() if code == 0 else ""

    if not base:
        return []

    _, stdout, _ = run(
        ["git", "diff", "--name-only", "--diff-filter=AM", base, "HEAD"],
        cwd=REPO_ROOT,
    )

    changed: list[Path] = []
    for line in stdout.splitlines():
        rel = line.strip()
        if not rel:
            continue
        normalised = rel.replace("\\", "/")
        if "/alembic/versions/" not in normalised:
            continue
        full = REPO_ROOT / normalised
        if full.is_file():
            changed.append(full)
    return changed


def check_tests() -> None:
    """Run the migration guard tests. Cheap, and they are the CI gate."""
    section("6. Migration guard tests")
    code, stdout, stderr = run(
        [sys.executable, "-m", "pytest", "tests/test_migration_heads.py", "-q"],
        cwd=API_DIR,
    )
    output = (stdout + stderr).strip()
    summary = [line for line in output.splitlines() if "passed" in line or "failed" in line]

    if code != 0:
        record(FAIL, "migration guard tests", summary[-1] if summary else "failed", [output[-1500:]])
        print(f"    {output[-800:]}")
        return

    record(PASS, "migration guard tests", summary[-1] if summary else "passed")
    print(f"    {summary[-1] if summary else 'passed'}")


def check_branch_is_reachable() -> None:
    """The branch being pushed must already contain origin/staging's commits.

    ``development`` is normally *behind* ``staging`` by design - staging gets
    merge commits that development does not have. That is not a problem.

    What IS a problem is the reverse: origin/staging containing work that this
    branch does not have. That means pushing this branch would deploy an
    older build than what is already live, silently rolling back fixes.

    The check asks a content question rather than a graph question: are there
    commits on origin/staging that are NOT already in this branch, ignoring
    merge commits?

    Merge commits are excluded because staging legitimately contains merge
    commits from PRs that brought development in. Those merge commits are
    "not in development" by graph but contain nothing that would be lost.

    Two distinct signals come out of this:

    - **Deploying this branch would lose work** (blocking). Only relevant
      when the push target is staging, because a push to development does
      not deploy anything and a merge into staging keeps both sides.
    - **Staging has hotfixes development does not have** (informational).
      These survive a merge into staging, but they should be back-ported to
      development or they will be re-broken the next time development is
      merged forward.
    """
    section("7. Branch vs origin/staging")
    code, stdout, _ = run(
        ["git", "rev-parse", "--verify", "origin/staging"], cwd=REPO_ROOT
    )
    if code != 0:
        record(WARN, "branch freshness", "origin/staging not fetched; run git fetch")
        print("    origin/staging not fetched (run git fetch) - skipping")
        return

    _, ahead_out, _ = run(
        ["git", "rev-list", "--count", "origin/staging..HEAD"], cwd=REPO_ROOT
    )
    ahead = ahead_out.strip() or "0"

    # Non-merge commits on staging that this branch does not contain.
    code, missing_out, _ = run(
        ["git", "log", "origin/staging", "--not", "HEAD", "--no-merges",
         "--oneline", "--format=%h %s"],
        cwd=REPO_ROOT,
    )
    missing = [line for line in missing_out.splitlines() if line.strip()]

    if not missing:
        record(
            PASS,
            "branch freshness",
            f"{ahead} commit(s) ahead, nothing on staging is missing",
        )
        print(f"    {ahead} commit(s) ahead, nothing on staging is missing")
        return

    # Deploying this branch would ship a build without those commits.
    if _push_target_is_staging():
        record(
            FAIL,
            "branch freshness",
            f"{len(missing)} staging commit(s) missing from this branch",
            [
                f"{line} - staging has this but the branch does not. "
                f"Deploying now would ship a build that is missing it."
                for line in missing[:10]
            ],
        )
        for line in missing[:10]:
            print(f"    - {line}")
        return

    record(
        WARN,
        "branch freshness",
        f"{ahead} commit(s) ahead, {len(missing)} staging-only commit(s) to back-port",
        [
            f"{line} - exists on staging only. A merge into staging keeps it, "
            f"but it should be back-ported to development."
            for line in missing[:10]
        ],
    )
    for line in missing[:10]:
        print(f"    - {line}")


def _push_target_is_staging() -> bool:
    """True when this push would land on the staging branch.

    A push to development does not deploy, and a PR merge into staging keeps
    both sides, so the blocking variant only applies to a direct push to
    staging.
    """
    code, branch_out, _ = run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=REPO_ROOT
    )
    return code == 0 and branch_out.strip() == "staging"


def check_no_secrets() -> None:
    """Refuse to push obvious secrets in staged/uncommitted files."""
    section("8. No secrets in the working tree")
    patterns = [
        r"AKIA[0-9A-Z]{16}",                      # AWS access key
        r"gh[pousr]_[A-Za-z0-9]{36,}",            # GitHub token
        r"sk-[A-Za-z0-9]{32,}",                   # OpenAI-style key
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",    # private key
    ]
    code, stdout, _ = run(
        ["git", "status", "--porcelain"], cwd=REPO_ROOT
    )
    if code != 0:
        record(WARN, "secrets", "could not read git status")
        return

    import re

    findings: list[str] = []
    for line in stdout.splitlines():
        path = line[3:].strip().strip('"')
        if not path or path.startswith("services/api/alembic/versions/"):
            continue
        full = REPO_ROOT / path
        if not full.is_file() or full.stat().st_size > 2_000_000:
            continue
        try:
            content = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            if re.search(pattern, content):
                findings.append(f"{path}: matches {pattern}")

    if findings:
        record(FAIL, "secrets", f"{len(findings)} potential secret(s)", findings)
        for item in findings:
            print(f"    - {item}")
        return

    record(PASS, "secrets", "no obvious secrets in changed files")
    print("    no obvious secrets in changed files")


# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-db", action="store_true", help="skip database-touching checks")
    parser.add_argument("--quick", action="store_true", help="only run the fast structural checks")
    args = parser.parse_args()

    # app/config.py reads `env_file: ".env"` relative to the CWD. The repo
    # root has its own .env (docker/pg convenience vars) that the API's
    # Settings rejects with extra="forbidden", so importing app.database from
    # the repo root raises a ValidationError. Every API-side check has to run
    # from services/api, exactly like pytest does.
    os.chdir(API_DIR)

    print("=" * 70)
    print("PRE-PUSH CHECKLIST")
    print("=" * 70)
    print(f"repo:   {REPO_ROOT}")
    print(f"branch: {os.popen('git rev-parse --abbrev-ref HEAD').read().strip()}")

    check_migration_chain()
    check_model_drift()
    check_migration_files_changed()
    check_alembic_current()
    check_migrations_are_idempotent()

    if not args.quick:
        check_tests()
        check_branch_is_reachable()
        check_no_secrets()

    section("SUMMARY")
    failed = 0
    warned = 0
    for status, name, detail, notes in _results:
        marker = {PASS: "ok", FAIL: "FAIL", WARN: "warn"}[status]
        print(f"  [{marker:>4}] {name}: {detail}")
        for note in notes:
            print(f"          {note}")
        if status == FAIL:
            failed += 1
        elif status == WARN:
            warned += 1

    print()
    if failed:
        print(f"RESULT: FAILED ({failed} check(s) failed)")
        print("DO NOT PUSH. Fix the failures above first.")
        return 1

    print(f"RESULT: OK ({warned} warning(s))")
    if warned:
        print("Review the warnings above before pushing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
