"""Ask Sayvors chart datasets, chart validation and planner tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.assistant import chart_data, charts, memory
from app.modules.assistant.chart_data import query_dataset
from app.modules.analytics.models import (
    ChannelDailyMetric,
    LocationDailyMetric,
    ReviewInsight,
)
from app.modules.channels.models import (
    Channel,
    ChannelThread,
    Lead,
    ReviewReply,
)
from app.modules.jobs.models import Job
from app.modules.llm.models import LLMUsageEvent
from app.modules.llm.providers.base import LLMResponse, ToolCall


@pytest.fixture(autouse=True)
def _clear_memory_fallback():
    memory._fallback.clear()
    charts._tool_failures.clear()
    yield
    memory._fallback.clear()
    charts._tool_failures.clear()


async def _seed(db, user_id, channel_id):
    now = datetime.now(timezone.utc)
    db.add(Channel(
        id="chart-wa-0000-0000-0000-000000000001",
        user_id=user_id,
        platform="whatsapp",
        platform_user_id="wa-1",
        display_name="WhatsApp line",
        status="active",
    ))
    db.add(Channel(
        id="chart-other-0000-0000-0000-000000000002",
        user_id="another-tenant",
        platform="google_reviews",
        platform_user_id="other",
        display_name="Other tenant",
        status="active",
    ))
    await db.commit()

    for i, (rating, sentiment, day) in enumerate([
        (5, "positive", 2),
        (5, "positive", 1),
        (2, "negative", 0),
    ]):
        db.add(ReviewInsight(
            id=f"chart-review-{i}",
            user_id=user_id,
            channel_id=channel_id,
            review_id=f"review-{i}",
            rating=rating,
            review_text="ok",
            reviewer_name=f"Reviewer {i}",
            sentiment=sentiment,
            topics=[{"name": "service", "sentiment": sentiment}],
            review_updated_at=now - timedelta(days=day),
        ))
    db.add(ReviewInsight(
        id="chart-review-other",
        user_id="another-tenant",
        channel_id="chart-other-0000-0000-0000-000000000002",
        review_id="review-other",
        rating=1,
        review_text="not mine",
        reviewer_name="Other",
        sentiment="negative",
        review_updated_at=now,
    ))
    db.add(ReviewReply(
        id="chart-reply-1", channel_id=channel_id, review_id="review-0",
        rating=5, review_text="ok", reviewer_name="Reviewer 0",
        reply_text="Thanks!", status="posted",
    ))
    db.add(ChannelThread(
        id="chart-thread-1", channel_id=channel_id,
        contact_phone="966500000001", contact_phone_hash="hash-1",
        contact_name="Hamza", total_count=7, unread_count=2,
        category="complaint", priority="high",
        created_at=now - timedelta(days=1),
        last_message_at=now,
    ))
    db.add(ChannelThread(
        id="chart-thread-2", channel_id="chart-wa-0000-0000-0000-000000000001",
        contact_phone="966500000002", contact_phone_hash="hash-2",
        contact_name="Sara", total_count=3, unread_count=0,
        category="inquiry", priority="normal",
        created_at=now - timedelta(days=2),
        last_message_at=now,
    ))
    db.add(Lead(
        id="chart-lead-1", tenant_id=user_id, channel_id=channel_id,
        platform="google_reviews", contact_id="966500000001",
        contact_name="Hamza", stage="qualified", category="retail",
        created_at=now - timedelta(days=1),
    ))
    db.add(ChannelDailyMetric(
        id="chart-metric-1", user_id=user_id, channel_id=channel_id,
        date=now.date(), messages_in=10, messages_out=8,
        median_first_response_seconds=120, p90_first_response_seconds=300,
        followers_count=1200,
    ))
    db.add(LocationDailyMetric(
        id="chart-loc-1", user_id=user_id, channel_id=channel_id,
        date=now.date(), impressions_maps_desktop=100, impressions_maps_mobile=50,
        call_clicks=4, direction_requests=6, website_clicks=3,
        extra={"impressions_search": 25},
    ))
    db.add(LLMUsageEvent(
        id="chart-usage-1", tenant_id=user_id, provider="groq",
        model_id="groq:qwen", api_model="qwen", purpose="review_engine.generate",
        cost_cents=12, total_tokens=100,
        created_at=now - timedelta(days=1),
    ))
    db.add(Job(
        id="chart-job-1", tenant_id=user_id, job_type="post_publish",
        lane="publishing", status="succeeded", payload={}, lane_key="k",
        created_at=now - timedelta(days=1),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_chart_datasets_are_tenant_scoped_and_real(db, user_id, channel_id):
    await _seed(db, user_id, channel_id)

    review = await query_dataset(db, user_id, "review_volume", days=30)
    assert review["rows"]
    assert sum(r["reviews"] for r in review["rows"]) == 3
    assert review["suggested_type"] == "line"
    assert review["kpis"][0]["value"] == 3

    rating = await query_dataset(db, user_id, "rating_distribution", days=30)
    assert {(r["label"], r["reviews"]) for r in rating["rows"]} == {
        ("5 star", 2), ("2 star", 1),
    }

    sentiment = await query_dataset(db, user_id, "sentiment_distribution", days=30)
    assert {r["label"]: r["reviews"] for r in sentiment["rows"]} == {
        "Positive": 2, "Negative": 1,
    }

    topics = await query_dataset(db, user_id, "review_topics", days=30)
    assert topics["rows"][0]["label"] == "service"
    assert topics["rows"][0]["mentions"] == 3

    customers = await query_dataset(db, user_id, "customers_by_platform", days=30)
    assert {r["label"]: r["customers"] for r in customers["rows"]} == {
        "Google Business": 1, "WhatsApp": 1,
    }

    messages = await query_dataset(db, user_id, "message_volume", days=30)
    assert messages["rows"][0]["inbound"] == 10
    assert messages["rows"][0]["outbound"] == 8

    leads = await query_dataset(db, user_id, "lead_pipeline", days=30)
    assert {r["label"]: r["leads"] for r in leads["rows"]} == {"Qualified": 1}

    visibility = await query_dataset(db, user_id, "google_visibility", days=30)
    assert visibility["rows"][0]["impressions"] == 175

    spend = await query_dataset(db, user_id, "ai_spend_by_purpose", days=30)
    assert spend["rows"][0]["label"] == "Review reply"
    assert spend["rows"][0]["cost"] == 0.12

    # A filter that matches no channel is a real empty result, not every
    # tenant row.
    empty = await query_dataset(db, user_id, "review_volume", days=30, platform="instagram")
    assert empty["rows"] == []


def test_chart_builder_rejects_fabricated_fields_and_dedupes():
    dataset = {
        "dataset_id": "ds_test",
        "dataset": "review_volume",
        "domain": "reviews",
        "title": "Review volume",
        "query_key": "review_volume|30||",
        "window_days": 30,
        "suggested_x": "label",
        "suggested_series": ["reviews"],
        "columns": [
            {"key": "label", "label": "Date", "type": "date"},
            {"key": "reviews", "label": "Reviews", "type": "number"},
            {"key": "positive", "label": "Positive", "type": "number"},
        ],
        "rows": [
            {"label": "2026-11-01", "reviews": 4, "positive": 3},
            {"label": "2026-11-02", "reviews": 6, "positive": 5},
        ],
        "kpis": [{"label": "Reviews", "value": 10, "format": "number", "delta": None}],
    }
    context = {"review_volume|30||": dataset}
    made: list[dict] = []
    signatures: set[str] = set()

    first = charts._create_chart(
        {"dataset_id": "ds_test", "chart_type": "line", "title": "Reviews over time",
         "series": ["not_a_real_column"]},
        context, memory.empty_memory(), made, signatures,
    )
    assert first["created"] is True
    # Unknown series falls back to the dataset recommendation, never a fake key.
    assert made[0]["series"] == [{"key": "reviews", "label": "Reviews", "format": "number"}]
    assert made[0]["type"] == "line"

    duplicate = charts._create_chart(
        {"dataset_id": "ds_test", "chart_type": "line", "title": "Again"},
        context, memory.empty_memory(), made, signatures,
    )
    assert "already" in duplicate["error"]

    unknown = charts._create_chart(
        {"dataset_id": "ds_missing", "chart_type": "bar", "title": "Nope"},
        context, memory.empty_memory(), made, signatures,
    )
    assert "dataset_id" in unknown["error"]


def test_chart_type_is_resolved_to_the_data_shape():
    dataset = {
        "dataset": "rating_distribution", "domain": "reviews",
        "title": "Ratings", "query_key": "q", "window_days": 30,
        "suggested_x": "label", "suggested_series": ["reviews"],
        "columns": [
            {"key": "label", "label": "Rating", "type": "string"},
            {"key": "reviews", "label": "Reviews", "type": "number"},
        ],
        "rows": [{"label": "5 star", "reviews": 8}, {"label": "4 star", "reviews": 2}],
        "kpis": [],
    }
    donut = charts._build_chart(
        dataset, chart_type="donut", title="Ratings", subtitle=None,
        x="label", series=["reviews"], include_kpis=False,
    )
    assert donut["type"] == "donut"

    stacked = charts._build_chart(
        dataset, chart_type="stacked_bar", title="Ratings", subtitle=None,
        x="label", series=["reviews"], include_kpis=False,
    )
    # One series cannot be stacked; it degrades to a bar, not a broken chart.
    assert stacked["type"] == "bar"


def test_memory_recalls_recent_datasets_but_not_old_ones():
    mem = memory.empty_memory()
    ds = {
        "dataset_id": "ds_1", "dataset": "review_volume", "title": "Reviews",
        "query_key": "review_volume|30||", "rows": [{"label": "2026-11-01", "reviews": 1}],
        "columns": [], "kpis": [], "suggested_type": "line",
    }
    memory.remember_dataset(mem, ds)
    assert memory.recall_dataset(mem, "review_volume|30||")["dataset_id"] == "ds_1"

    mem["datasets"]["ds_1"]["created_at"] = 0
    assert memory.recall_dataset(mem, "review_volume|30||") is None


@pytest.mark.asyncio
async def test_memory_falls_back_when_redis_is_down(monkeypatch):
    from app.modules.redis import client as redis_client

    async def _down():
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis_client, "get_redis", _down)
    mem = memory.empty_memory()
    memory.append_turn(mem, "user", "How are reviews?")
    await memory.save_memory("tenant-1", "session-1", mem)
    loaded = await memory.load_memory("tenant-1", "session-1")
    assert loaded["turns"][0]["content"] == "How are reviews?"


@pytest.mark.asyncio
async def test_planner_calls_data_tools_and_builds_one_chart(
    db, user_id, channel_id, monkeypatch
):
    await _seed(db, user_id, channel_id)
    dataset_id = charts._dataset_id("review_volume|30||")
    calls = {"n": 0}

    async def fake_complete(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return LLMResponse(
                content="",
                provider="test",
                model="test",
                tool_calls=[ToolCall(
                    name="get_business_data",
                    arguments={"dataset": "review_volume", "days": 30},
                )],
            )
        if calls["n"] == 2:
            return LLMResponse(
                content="",
                provider="test",
                model="test",
                tool_calls=[ToolCall(
                    name="create_chart",
                    arguments={
                        "dataset_id": dataset_id,
                        "chart_type": "line",
                        "title": "Reviews over time",
                        "series": ["reviews"],
                    },
                )],
            )
        return LLMResponse(content="NO_CHART", provider="test", model="test")

    monkeypatch.setattr(charts, "complete", fake_complete)
    plan = await charts.plan_charts(
        db=db,
        user=type("U", (), {"id": user_id})(),
        tenant_id=user_id,
        model="test:model",
        message="Show me a chart of review volume over time",
        history=[],
        memory=memory.empty_memory(),
        business_context="Test Burgers",
    )
    assert len(plan.charts) == 1
    chart = plan.charts[0]
    assert chart["type"] == "line"
    assert chart["title"] == "Reviews over time"
    assert chart["rows"]
    assert plan.steps
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_planner_falls_back_to_json_when_tool_calls_are_rejected(
    db, user_id, channel_id, monkeypatch
):
    """Groq can reject a model-mangled tool call before the provider returns.
    The tools-disabled JSON plan must still produce a chart from real rows."""
    await _seed(db, user_id, channel_id)
    calls = {"n": 0}

    async def fake_complete(**kwargs):
        calls["n"] += 1
        if kwargs.get("tools"):
            raise RuntimeError("tool call validation failed")
        return LLMResponse(
            content=(
                '{"charts":[{"dataset":"rating_distribution","days":0,'
                '"type":"bar","title":"Rating distribution · all time",'
                '"include_kpis":true}]}'
            ),
            provider="test",
            model="test",
        )

    monkeypatch.setattr(charts, "complete", fake_complete)
    plan = await charts.plan_charts(
        db=db,
        user=type("U", (), {"id": user_id})(),
        tenant_id=user_id,
        model="test:model",
        message="Show me the rating distribution",
        history=[],
        memory=memory.empty_memory(),
        business_context="Test Burgers",
    )
    assert calls["n"] == 2
    assert len(plan.charts) == 1
    chart = plan.charts[0]
    assert chart["type"] == "bar"
    assert chart["dataset"] == "rating_distribution"
    assert sum(row["reviews"] for row in chart["rows"]) == 3
    assert chart["kpis"]
    assert plan.steps


@pytest.mark.asyncio
async def test_explicit_chart_request_builds_charts_when_planner_declines(
    db, user_id, channel_id, monkeypatch
):
    """The model sometimes answers "NO_CHART" to "make me charts".

    The owner still gets real interactive charts instead of the model drawing
    ASCII bars into the answer.
    """
    await _seed(db, user_id, channel_id)

    async def fake_complete(**kwargs):
        return LLMResponse(content="NO_CHART", provider="test", model="test")

    monkeypatch.setattr(charts, "complete", fake_complete)
    plan = await charts.plan_charts(
        db=db,
        user=user_id,
        tenant_id=user_id,
        model="test:model",
        message="please make me charts",
        history=[],
        memory=memory.empty_memory(),
        business_context="Test Burgers",
    )
    assert plan.charts, "an explicit chart request must not return zero charts"
    datasets = {c["dataset"] for c in plan.charts}
    assert "rating_distribution" in datasets
    assert "reviews_by_location" in datasets
    for chart in plan.charts:
        assert chart["rows"], f"{chart['dataset']} chart has no rows"
        assert chart["title"]


@pytest.mark.asyncio
async def test_explicit_heatmap_request_builds_heatmap_without_planner(
    db, user_id, channel_id, monkeypatch
):
    """A named chart type is an explicit visual request. Even if the model
    planner returns NO_CHART, the owner still gets that chart from real rows."""
    await _seed(db, user_id, channel_id)

    async def fake_complete(**kwargs):
        return LLMResponse(content="NO_CHART", provider="test", model="test")

    monkeypatch.setattr(charts, "complete", fake_complete)
    plan = await charts.plan_charts(
        db=db,
        user=user_id,
        tenant_id=user_id,
        model="test:model",
        message="make me a heatmap of when reviews arrive",
        history=[],
        memory=memory.empty_memory(),
        business_context="Test Burgers",
    )
    heatmaps = [c for c in plan.charts if c["type"] == "heatmap"]
    assert heatmaps, [c["type"] for c in plan.charts]
    assert heatmaps[0]["rows"]
    assert heatmaps[0]["y_values"]


@pytest.mark.asyncio
async def test_vague_question_does_not_get_a_forced_chart(
    db, user_id, channel_id, monkeypatch
):
    """'How is my performance?' may use the planner, but a 'no chart' verdict
    must be respected — the auto plan is only for explicit visual requests."""
    await _seed(db, user_id, channel_id)

    async def fake_complete(**kwargs):
        return LLMResponse(content="NO_CHART", provider="test", model="test")

    monkeypatch.setattr(charts, "complete", fake_complete)
    plan = await charts.plan_charts(
        db=db,
        user=user_id,
        tenant_id=user_id,
        model="test:model",
        message="how is my performance?",
        history=[],
        memory=memory.empty_memory(),
        business_context="Test Burgers",
    )
    assert plan.charts == []


@pytest.mark.asyncio
async def test_review_heatmap_dataset_has_day_hour_cells(db, user_id, channel_id):
    await _seed(db, user_id, channel_id)
    result = await query_dataset(db, user_id, "review_heatmap", days=0)
    assert result["rows"], "heatmap should have cells for seeded reviews"
    assert result.get("heatmap") is True
    row = result["rows"][0]
    assert set(row) >= {"label", "x", "y", "value"}
    assert int(row["value"]) >= 1
    assert row["y"] in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


@pytest.mark.asyncio
async def test_heatmap_chart_builds_ordered_grid(db, user_id, channel_id, monkeypatch):
    await _seed(db, user_id, channel_id)

    async def fake_complete(**kwargs):
        return LLMResponse(
            content=(
                '{"charts":[{"dataset":"review_heatmap","days":0,"type":"heatmap",'
                '"title":"When reviews arrive"}]}'
            ),
            provider="test",
            model="test",
        )

    monkeypatch.setattr(charts, "complete", fake_complete)
    plan = await charts.plan_charts(
        db=db,
        user=user_id,
        tenant_id=user_id,
        model="test:model",
        message="make me a heatmap of when reviews arrive",
        history=[],
        memory=memory.empty_memory(),
        business_context="Test Burgers",
    )
    heatmaps = [c for c in plan.charts if c["type"] == "heatmap"]
    assert heatmaps, [c["type"] for c in plan.charts]
    chart = heatmaps[0]
    assert chart["x_values"] == sorted(chart["x_values"], key=int)
    assert chart["y_values"]
    assert all("value" in row for row in chart["rows"])


@pytest.mark.asyncio
async def test_radar_chart_builds_from_sentiment_by_location(
    db, user_id, channel_id, monkeypatch
):
    await _seed(db, user_id, channel_id)

    async def fake_complete(**kwargs):
        return LLMResponse(
            content=(
                '{"charts":[{"dataset":"sentiment_by_location","days":0,"type":"radar",'
                '"title":"Sentiment by location"}]}'
            ),
            provider="test",
            model="test",
        )

    monkeypatch.setattr(charts, "complete", fake_complete)
    plan = await charts.plan_charts(
        db=db,
        user=user_id,
        tenant_id=user_id,
        model="test:model",
        message="make me a radar chart of sentiment by location",
        history=[],
        memory=memory.empty_memory(),
        business_context="Test Burgers",
    )
    assert plan.charts
    chart = plan.charts[0]
    assert chart["type"] == "radar"
    assert {s["key"] for s in chart["series"]} == {"positive", "neutral", "negative"}
    assert chart["rows"]
