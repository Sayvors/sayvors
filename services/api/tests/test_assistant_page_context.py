"""Ask Sayvors screen context: resolve benchmark compare selection to names."""
import pytest

from app.modules.assistant.router import _page_context

pytestmark = pytest.mark.asyncio


async def test_page_context_compare_resolves_saved_and_own(db, channel_id, user_id):
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(
        db, user_id, place_id="cmp-alpha", label="Alpha Eatery"
    )
    page = (
        "/dashboard/benchmark/compare"
        f"?main=own:{channel_id}"
        "&vs=saved:cmp-alpha"
    )
    ctx = await _page_context(db, user_id, page)
    assert "Benchmark · Compare" in ctx
    assert "Test Burgers" in ctx          # own channel display name
    assert "Alpha Eatery" in ctx          # saved place label
    assert "compared right now are" in ctx


async def test_page_context_compare_hides_other_tenant_names(db, channel_id, user_id, other_user_id):
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(
        db, other_user_id, place_id="cmp-other", label="Secret Rival"
    )
    page = "/dashboard/benchmark/compare?vs=saved:cmp-other"
    ctx = await _page_context(db, user_id, page)
    assert "Secret Rival" not in ctx
    assert "a business" in ctx  # falls back to a neutral placeholder


async def test_page_context_unknown_page_is_empty():
    ctx = await _page_context(None, "t", "/dashboard/unknown-page")
    assert ctx == ""
    assert await _page_context(None, "t", None) == ""


async def test_page_context_plain_page_label_only():
    ctx = await _page_context(None, "t", "/dashboard/benchmark")
    assert ctx == "The owner is on the Benchmark page."
