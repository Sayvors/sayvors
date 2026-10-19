"""Migration chain and model/migration drift guards.

Two failure modes this file exists to prevent:

1. **A forked migration chain.** Two migrations pointing at the same parent
   produce two heads, and ``alembic upgrade head`` on the container refuses
   to run ("Multiple head revisions are present"). The container then
   crash-loops on every deploy.

2. **A model column with no migration.** The model says the column exists,
   the database says it does not, and the first request that selects it
   fails with "column X does not exist" — after the container booted fine.

Both checks are structural, not behavioural, so they run without a database.
"""
import os
import re
from pathlib import Path

import pytest

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _read_migrations() -> dict[str, tuple[str | None, tuple[str, ...]]]:
    """Map revision id -> (filename, parents). Parents is a tuple so a merge
    revision (two down_revisions) is represented honestly."""
    out: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", src, re.M)
        if not rev:
            pytest.fail(f"{path.name} has no revision id")
        down = re.search(
            r"^down_revision(?::[^=]*)?\s*=\s*(\(.*?\)|[^(\n]+)", src, re.M | re.S
        )
        parents: tuple[str, ...] = ()
        if down:
            raw = down.group(1).strip()
            if raw.startswith("("):
                parents = tuple(re.findall(r"['\"]([^'\"]+)['\"]", raw))
            else:
                one = re.search(r"['\"]([^'\"]+)['\"]", raw)
                parents = (one.group(1),) if one else ()
        out[rev.group(1)] = (path.name, parents)
    return out


def test_no_duplicate_revision_ids():
    """Two files claiming the same revision id makes alembic refuse to run."""
    seen: dict[str, str] = {}
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)['\"]", src, re.M)
        if not rev:
            pytest.fail(f"{path.name} has no revision id")
        rid = rev.group(1)
        assert rid not in seen, (
            f"revision id {rid} is used by both {seen[rid]} and {path.name}"
        )
        seen[rid] = path.name


def test_migration_chain_has_exactly_one_head():
    """A forked chain has 2+ heads; `alembic upgrade head` then refuses."""
    migrations = _read_migrations()
    all_parents: set[str] = set()
    for _rid, (_fn, parents) in migrations.items():
        all_parents.update(parents)
    heads = sorted(r for r in migrations if r not in all_parents)
    assert len(heads) == 1, (
        f"alembic has {len(heads)} heads {heads} — chain forked. "
        f"A new migration must set down_revision to the CURRENT head, "
        f"not to an already-used parent."
    )


def test_no_orphan_down_revisions():
    """Every down_revision must name a migration that exists."""
    migrations = _read_migrations()
    for rid, (fn, parents) in migrations.items():
        for p in parents:
            assert p in migrations, (
                f"{fn} (revision {rid}) has down_revision {p} which does not exist"
            )


def test_model_columns_have_migrations():
    """Every column on a migrated table must be created by some migration.

    A column that exists only in the model is the "column X does not exist"
    class of deploy failure: the container boots, then the first request
    that touches the column 500s.
    """
    from app.database import Base

    # Import every model module so Base.metadata is complete.
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
    import app.modules.users.models  # noqa: F401

    # Every identifier that appears anywhere in any migration.
    migrated_tokens: set[str] = set()
    for path in VERSIONS_DIR.glob("*.py"):
        if path.name == "__init__.py":
            continue
        src = path.read_text(encoding="utf-8")
        migrated_tokens.update(re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", src))

    # Tables that are created outside alembic (test bootstrap, extensions).
    unmanaged = {
        "alembic_version",
        "alembic_tmp_reviews_issues",
    }

    missing: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name in unmanaged:
            continue
        for col in table.columns:
            # A column added by a migration names the column in that migration.
            if col.name not in migrated_tokens:
                missing.append(f"{table.name}.{col.name}")

    assert not missing, (
        "model columns with no migration: "
        + ", ".join(sorted(missing))
        + " — add an alembic migration for each"
    )