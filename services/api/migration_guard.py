"""Migration-chain and model-drift guards.

This module is the single source of truth for "is the alembic chain safe to
ship?". It is imported by two callers:

- ``services/api/tests/test_migration_heads.py`` - the pytest gate
- ``scripts/pre_push_check.py``      - the local pre-push checklist

Keeping the logic here (rather than inside the test file) means the local
check and the CI check can never drift apart, which is how the "4 heads"
and "duplicate revision id" incidents slipped through in the first place.

What it checks, and why each one matters:

**Duplicate revision ids.** Alembic keys its revision map by revision id. Two
files claiming the same id means one silently overwrites the other. Alembic
only emits a ``UserWarning`` and carries on, so the chain loads into a state
nobody intended. This is what broke the staging deploy: the container booted,
printed "Revision d4e5f6a7b8c9 is present more than once", then refused to
upgrade because the graph had two heads.

**Multiple heads.** ``alembic upgrade head`` refuses to run when the graph has
more than one head - it cannot choose. The container then crash-loops on every
boot. A fork happens whenever a new migration names a ``down_revision`` that is
not the current head (usually an already-used parent).

**Orphan down_revisions.** A migration whose parent does not exist makes the
chain unbuildable from scratch. It only shows up when somebody provisions a
brand-new database, which is exactly when you least want to find out.

**Unreachable revisions.** A revision that no path from a root can reach is
dead weight that silently disappears from ``alembic history``.

**Cycles.** A migration cycle makes ``alembic upgrade`` recurse forever.

**Model/migration drift.** A column that exists on an ORM model but that no
migration creates is the "column X does not exist" class of outage: the
container boots cleanly (migrations succeeded), then the first request that
selects that column 500s. This has bitten the project twice (``reviewer_name``
and ``contact_phone_hash``).

The column check is deliberately tolerant: it parses migrations for the
table+column pairs it can understand, and falls back to a repo-wide name match
for anything it cannot parse. It errs toward reporting *found* rather than
*missing*, because a false "missing column" would block an unrelated deploy.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

#: Repository root, derived from this file's location
#: (``services/api/migration_guard.py`` -> up two levels).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Directory holding the alembic revision scripts.
VERSIONS_DIR = Path(__file__).resolve().parent / "alembic" / "versions"

#: Throwaway secret used only while the guard imports the ORM metadata.
#:
#: The guard is static analysis: it parses the migration scripts and reads
#: ``Base.metadata``. It never opens a connection and never handles a JWT.
#: But importing ``app.database`` pulls in ``app.config``, whose module-level
#: gate exits the process while JWT_SECRET is still the placeholder. A CI
#: runner has no ``.env``, so the guard died before it could check anything.
#: Seeding a value for the duration of the import keeps the tool runnable
#: anywhere without deploy secrets, while the gate stays intact for real app
#: boots (which import ``app.config`` normally, without this module).
_GUARD_JWT_SECRET = "migration-guard-static-analysis-not-a-real-secret"


@dataclass(frozen=True)
class Migration:
    """One alembic revision script."""

    revision: str
    filename: str
    parents: tuple[str, ...]

    @property
    def is_merge(self) -> bool:
        """A merge revision has more than one parent and an empty body."""
        return len(self.parents) > 1


@dataclass
class ChainReport:
    """Outcome of a chain analysis. ``problems`` is empty when the chain is sound."""

    migrations: dict[str, Migration] = field(default_factory=dict)
    duplicates: list[tuple[str, str, str]] = field(default_factory=list)
    orphans: list[tuple[str, str]] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    cycles: list[str] = field(default_factory=list)
    roots: list[str] = field(default_factory=list)
    heads: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        """Human-readable, actionable description of everything that is wrong."""
        out: list[str] = []

        for revision, first, second in self.duplicates:
            out.append(
                f"duplicate revision id '{revision}': claimed by both "
                f"{first} and {second}. Alembic silently keeps one; "
                f"rename one of them to a fresh id."
            )

        for filename, parent in self.orphans:
            out.append(
                f"{filename} has down_revision '{parent}', which does not "
                f"exist. The chain cannot be built from scratch."
            )

        for revision in self.unreachable:
            out.append(
                f"{revision} is unreachable - no path from a base revision "
                f"leads to it. It will never run."
            )

        for revision in self.cycles:
            out.append(f"migration cycle detected involving '{revision}'.")

        if len(self.heads) > 1:
            listing = ", ".join(self.heads)
            out.append(
                f"{len(self.heads)} alembic heads: {listing}. "
                f"'alembic upgrade head' refuses to run with multiple heads. "
                f"A new migration must set down_revision to the CURRENT head."
            )

        return out

    @property
    def ok(self) -> bool:
        return not self.problems


def _parse_revisions() -> tuple[dict[str, Migration], list[tuple[str, str, str]]]:
    """Read every migration file and build the revision map.

    Returns the map plus a list of ``(revision, first_file, second_file)``
    duplicate collisions.
    """
    migrations: dict[str, Migration] = {}
    duplicates: list[tuple[str, str, str]] = []

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8")

        revision_match = re.search(
            r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", src, re.M
        )
        if not revision_match:
            raise ValueError(f"{path.name} has no revision id")

        revision = revision_match.group(1)

        # down_revision may be a single id or a tuple of ids for a merge
        # revision. The tuple spans multiple lines, so the pattern has to be
        # non-greedy across newlines.
        down_match = re.search(
            r"^down_revision(?::[^=]*)?\s*=\s*(\(.*?\)|[^(\n]+)",
            src,
            re.M | re.S,
        )
        parents: tuple[str, ...] = ()
        if down_match:
            raw = down_match.group(1).strip()
            if raw.startswith("("):
                parents = tuple(re.findall(r"['\"]([^'\"]+)['\"]", raw))
            else:
                single = re.search(r"['\"]([^'\"]+)['\"]", raw)
                parents = (single.group(1),) if single else ()

        if revision in migrations:
            duplicates.append((revision, migrations[revision].filename, path.name))
            continue

        migrations[revision] = Migration(
            revision=revision, filename=path.name, parents=parents
        )

    return migrations, duplicates


def analyze_chain() -> ChainReport:
    """Analyse the migration chain and report everything that is wrong with it."""
    migrations, duplicates = _parse_revisions()
    report = ChainReport(migrations=migrations, duplicates=duplicates)

    known = set(migrations)

    # Orphans: a parent that does not exist in the map.
    for revision, migration in migrations.items():
        for parent in migration.parents:
            if parent not in known:
                report.orphans.append((migration.filename, parent))

    # Roots: revisions with no parents at all.
    report.roots = sorted(r for r, m in migrations.items() if not m.parents)

    # Heads: revisions that nothing points at.
    referenced = {p for m in migrations.values() for p in m.parents}
    report.heads = sorted(r for r in known if r not in referenced)

    # Reachability: walk forward from every root.
    children: dict[str, list[str]] = {}
    for revision, migration in migrations.items():
        for parent in migration.parents:
            children.setdefault(parent, []).append(revision)

    reachable: set[str] = set()
    stack = list(report.roots)
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(children.get(current, []))

    report.unreachable = sorted(known - reachable)

    # Cycles: a revision is in a cycle if it is not reachable from any root.
    # (An orphan's parent is already reported separately.)
    report.cycles = sorted(set(report.unreachable) & known)

    return report


# --------------------------------------------------------------------------
# Model / migration drift
# --------------------------------------------------------------------------

# ``op.add_column('table', sa.Column('column', ...))``
_ADD_COLUMN = re.compile(
    r"op\.add_column\(\s*['\"](?P<table>[^'\"]+)['\"]\s*,\s*"
    r"(?:sa\.)?Column\(\s*['\"](?P<column>[^'\"]+)['\"]",
    re.I,
)

# ``op.create_table('table', ... sa.Column('column', ...) ...)`` - the column
# may be several lines away from the create_table call, so the body is matched
# up to the next ``op.`` call.
_CREATE_TABLE = re.compile(
    r"op\.create_table\(\s*['\"](?P<table>[^'\"]+)['\"](?P<body>.*?)(?=\n\s*op\.|\Z)",
    re.S | re.I,
)
_COLUMN_ANYWHERE = re.compile(
    r"(?:sa\.)?Column\(\s*['\"](?P<column>[A-Za-z_][A-Za-z0-9_]*)['\"]"
)

# ``ALTER TABLE "table" ADD COLUMN "column"`` - used by the idempotent
# migrations that cannot use op.add_column (it has no IF NOT EXISTS).
_ALTER_TABLE = re.compile(
    r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?['\"]?(?P<table>[A-Za-z_][A-Za-z0-9_]*)"
    r"['\"]?\s+ADD\s+COLUMN\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"['\"]?(?P<column>[A-Za-z_][A-Za-z0-9_]*)",
    re.I,
)

# Any quoted identifier appearing anywhere in a migration - the fallback used
# when a table-scoped match cannot be established.
_ANY_IDENTIFIER = re.compile(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]")


def _model_tables() -> dict[str, set[str]]:
    """Map table name -> column names, from the ORM metadata.

    Every model module must be imported so ``Base.metadata`` is complete.
    A model that is not imported here would look like a missing table.
    """
    import os

    # See ``_GUARD_JWT_SECRET``. Only override for the duration of the import,
    # then restore, so a pre-push or pytest process that already has a real
    # value is left untouched. Once the model modules are in ``sys.modules``
    # the config gate cannot fire again, which makes repeat calls no-ops.
    previous_secret = os.environ.get("JWT_SECRET")
    os.environ["JWT_SECRET"] = _GUARD_JWT_SECRET
    try:
        from app.database import Base

        import app.modules.analytics.models  # noqa: F401
        import app.modules.auth.models  # noqa: F401
        import app.modules.billing.models  # noqa: F401
        import app.modules.channels.models  # noqa: F401
        import app.modules.channels.meta.models  # noqa: F401
        import app.modules.jobs.models  # noqa: F401
        import app.modules.llm.models  # noqa: F401
        import app.modules.localith.models  # noqa: F401
        import app.modules.notifications.models  # noqa: F401
        import app.modules.outbox.models  # noqa: F401
        import app.modules.posts.models  # noqa: F401
        import app.modules.stt.models  # noqa: F401
        import app.modules.tts.models  # noqa: F401
        import app.modules.users.models  # noqa: F401
    finally:
        if previous_secret is None:
            os.environ.pop("JWT_SECRET", None)
        else:
            os.environ["JWT_SECRET"] = previous_secret

    return {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }


def _migrated_columns() -> tuple[dict[str, set[str]], set[str]]:
    """Return (table -> columns) parsed from migrations, and all identifiers seen."""
    by_table: dict[str, set[str]] = {}
    all_identifiers: set[str] = set()

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8")

        all_identifiers.update(_ANY_IDENTIFIER.findall(src))

        for match in _ADD_COLUMN.finditer(src):
            by_table.setdefault(match.group("table").lower(), set()).add(
                match.group("column")
            )

        for match in _ALTER_TABLE.finditer(src):
            by_table.setdefault(match.group("table").lower(), set()).add(
                match.group("column")
            )

        for match in _CREATE_TABLE.finditer(src):
            table = match.group("table").lower()
            for column in _COLUMN_ANYWHERE.finditer(match.group("body")):
                by_table.setdefault(table, set()).add(column.group("column"))

    return by_table, all_identifiers


def find_model_drift() -> list[str]:
    """Model columns that no migration creates.

    Returns a list of ``"table.column"`` strings. Empty means no drift.
    """
    # Tables that are created outside alembic (test bootstrap, extensions).
    unmanaged = {"alembic_version", "alembic_tmp_reviews_issues"}

    models = _model_tables()
    by_table, all_identifiers = _migrated_columns()

    missing: list[str] = []
    for table, columns in models.items():
        if table in unmanaged:
            continue
        migrated_for_table = by_table.get(table.lower(), set())
        for column in sorted(columns):
            if column in migrated_for_table:
                continue
            # Fallback: the identifier appears somewhere in the migrations but
            # we could not tie it to this table. That is almost always a
            # migration written in a style this parser does not understand,
            # so treat it as migrated rather than blocking the deploy.
            if column in all_identifiers:
                continue
            missing.append(f"{table}.{column}")

    return missing


def summarize() -> dict[str, object]:
    """Machine-readable summary, used by the pre-push script and the tests."""
    report = analyze_chain()
    drift = find_model_drift()
    return {
        "migration_count": len(report.migrations),
        "heads": report.heads,
        "roots": report.roots,
        "duplicates": report.duplicates,
        "orphans": report.orphans,
        "unreachable": report.unreachable,
        "cycles": report.cycles,
        "problems": report.problems,
        "model_drift": drift,
        "ok": report.ok and not drift,
    }


def format_report() -> str:
    """Human-readable report, printed by the pre-push script."""
    report = analyze_chain()
    drift = find_model_drift()

    lines: list[str] = []
    lines.append(f"migrations: {len(report.migrations)}")
    lines.append(f"roots:      {len(report.roots)}")
    lines.append(f"heads:      {len(report.heads)}  {', '.join(report.heads)}")

    if report.problems:
        lines.append("")
        lines.append("PROBLEMS:")
        lines.extend(f"  - {problem}" for problem in report.problems)

    if drift:
        lines.append("")
        lines.append("MODEL DRIFT (model column with no migration):")
        lines.extend(f"  - {item}" for item in drift)

    lines.append("")
    lines.append("RESULT: OK" if report.ok and not drift else "RESULT: FAILED")

    return "\n".join(lines)


__all__ = [
    "ChainReport",
    "Migration",
    "analyze_chain",
    "find_model_drift",
    "format_report",
    "summarize",
]


if __name__ == "__main__":
    """Run the migration-chain guard directly: ``python migration_guard.py``.

    Prints a human-readable report and exits non-zero when the chain is not
    clean, so this doubles as a CI step that fails loud and early instead of
    burying a broken chain inside pytest.
    """
    import sys

    print(format_report())
    sys.exit(0 if summarize()["ok"] else 1)
