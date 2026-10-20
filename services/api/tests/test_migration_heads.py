"""Migration chain and model/migration drift guards.

Two failure modes this file exists to prevent:

1. **A forked migration chain.** Two migrations pointing at the same parent
   produce two heads, and ``alembic upgrade head`` on the container refuses
   to run ("Multiple head revisions are present"). The container then
   crash-loops on every deploy.

2. **A model column with no migration.** The model says the column exists,
   the database says it does not, and the first request that selects it
   fails with "column X does not exist" - after the container booted fine.

Both checks are structural, not behavioural, so they run without a database.

The analysis itself lives in ``services/api/migration_guard.py`` so that this
pytest gate and ``scripts/pre_push_check.py`` cannot drift apart. When the
guard logic changes, both callers change together.
"""
import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import migration_guard as guard  # noqa: E402


def test_no_duplicate_revision_ids():
    """Two files claiming the same revision id makes alembic refuse to run.

    Alembic keys its revision map by id, so the second file silently
    overwrites the first and the loaded graph is not what anyone intended.
    It only surfaces as a ``UserWarning`` and a wrong head count.
    """
    report = guard.analyze_chain()
    assert not report.duplicates, (
        "duplicate revision id(s): "
        + "; ".join(f"{rev} used by {a} and {b}" for rev, a, b in report.duplicates)
        + " - rename one of them to a fresh id"
    )


def test_migration_chain_has_exactly_one_head():
    """A forked chain has 2+ heads; `alembic upgrade head` then refuses."""
    report = guard.analyze_chain()
    assert len(report.heads) == 1, (
        f"alembic has {len(report.heads)} heads {report.heads} - chain forked. "
        f"A new migration must set down_revision to the CURRENT head, "
        f"not to an already-used parent."
    )


def test_no_orphan_down_revisions():
    """Every down_revision must name a migration that exists.

    An orphan only shows up when somebody provisions a brand-new database,
    which is the worst possible time to discover it.
    """
    report = guard.analyze_chain()
    assert not report.orphans, (
        "orphan down_revision(s): "
        + "; ".join(f"{fn} -> {parent}" for fn, parent in report.orphans)
    )


def test_every_revision_is_reachable():
    """A revision no path from a base reaches would never run."""
    report = guard.analyze_chain()
    assert not report.unreachable, (
        f"unreachable migration(s): {report.unreachable} - they would never run"
    )


def test_no_migration_cycles():
    """A cycle makes `alembic upgrade` recurse forever."""
    report = guard.analyze_chain()
    assert not report.cycles, f"migration cycle(s) detected: {report.cycles}"


def test_model_columns_have_migrations():
    """Every column on a migrated table must be created by some migration.

    A column that exists only in the model is the "column X does not exist"
    class of deploy failure: the container boots, then the first request
    that touches the column 500s.
    """
    missing = guard.find_model_drift()
    assert not missing, (
        "model columns with no migration: "
        + ", ".join(missing)
        + " - add an alembic migration for each"
    )


def test_chain_report_is_clean():
    """Catch anything the individual assertions above might not cover.

    ``problems`` is the aggregate of every structural problem the guard can
    find, so this stays correct as new checks are added to the guard.
    """
    report = guard.analyze_chain()
    assert report.ok, "migration chain problems:\n- " + "\n- ".join(report.problems)


def test_alembic_actually_loads_a_single_head():
    """The guard's own analysis must agree with what alembic reports.

    This is the end-to-end version of the above: it runs alembic's real
    script loader, so a migration file with syntax alembic cannot parse
    (or a revision id alembic rejects) is caught too.
    """
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=str(API_DIR),
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = proc.stdout + proc.stderr

    assert "present more than once" not in output, (
        "alembic reports a duplicate revision id:\n" + output
    )

    heads = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, f"alembic reports {len(heads)} heads: {heads}\n{output}"


@pytest.mark.parametrize(
    "scenario",
    ["duplicate_id", "fork", "orphan"],
)
def test_guard_detects_each_failure_mode(scenario, tmp_path, monkeypatch):
    """The guard must actually catch the failure it exists to catch.

    A guard that cannot fail is worse than no guard, because it gives
    false confidence. This writes a deliberately broken migration into a
    temporary versions directory and asserts the guard reports it.
    """
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "__init__.py").write_text("")

    good = (
        "revision: str = 'aaa000000001'\n"
        "down_revision: Union[str, None] = None\n"
    )

    if scenario == "duplicate_id":
        # Two files, same revision id.
        (versions / "a_one.py").write_text(good)
        (versions / "b_two.py").write_text(
            good.replace("aaa000000001", "bbb000000002")
        )
        (versions / "c_dup.py").write_text(good)
        expected = "duplicate revision id"
    elif scenario == "fork":
        # Two children of the same parent.
        (versions / "a_root.py").write_text(good)
        (versions / "b_left.py").write_text(
            good.replace("aaa000000001", "bbb000000002")
            .replace("Union[str, None] = None", "Union[str, None] = 'aaa000000001'")
        )
        (versions / "c_right.py").write_text(
            good.replace("aaa000000001", "ccc000000003")
            .replace("Union[str, None] = None", "Union[str, None] = 'aaa000000001'")
        )
        expected = "alembic heads"
    else:  # orphan
        (versions / "a_root.py").write_text(good)
        (versions / "b_orphan.py").write_text(
            good.replace("aaa000000001", "bbb000000002")
            .replace("Union[str, None] = None", "Union[str, None] = 'missing_rev'")
        )
        expected = "does not exist"

    monkeypatch.setattr(guard, "VERSIONS_DIR", versions)
    report = guard.analyze_chain()

    assert any(expected in problem for problem in report.problems), (
        f"guard did not detect the {scenario} scenario; "
        f"problems were: {report.problems}"
    )
