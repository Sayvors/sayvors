"""Benchmark-set membership: toggle, cap, and serialization (no network)."""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.modules.benchmark import service


@pytest.mark.asyncio
async def test_place_defaults_out_of_set(db, user_id):
    await service.save_place(db, user_id, place_id="p1", label="One")
    saved = await service.get_saved(db, user_id, "p1")
    assert saved.in_bench_set is False


@pytest.mark.asyncio
async def test_toggle_and_serialize(db, user_id):
    await service.save_place(db, user_id, place_id="p1", label="One")
    row = await service.set_bench_set(db, user_id, "p1", enabled=True)
    assert row.in_bench_set is True
    assert service.serialize(row)["in_bench_set"] is True
    row = await service.set_bench_set(db, user_id, "p1", enabled=False)
    assert row.in_bench_set is False


@pytest.mark.asyncio
async def test_toggle_unknown_place_raises(db, user_id):
    with pytest.raises(service.BenchError):
        await service.set_bench_set(db, user_id, "nope", enabled=True)


@pytest.mark.asyncio
async def test_set_cap_is_five(db, user_id):
    for i in range(5):
        await service.save_place(db, user_id, place_id=f"p{i}", label=str(i))
        await service.set_bench_set(db, user_id, f"p{i}", enabled=True)
    await service.save_place(db, user_id, place_id="p5", label="Sixth")
    with pytest.raises(service.BenchError, match="full"):
        await service.set_bench_set(db, user_id, "p5", enabled=True)
    # Toggling off still works at the cap, and re-enabling a member is a no-op.
    await service.set_bench_set(db, user_id, "p4", enabled=False)
    await service.set_bench_set(db, user_id, "p5", enabled=True)


@pytest.mark.asyncio
async def test_list_saved_carries_flag(db, user_id):
    await service.save_place(db, user_id, place_id="p1", label="One")
    await service.set_bench_set(db, user_id, "p1", enabled=True)
    rows = await service.list_saved(db, user_id, limit=10)
    assert rows[0]["in_bench_set"] is True
