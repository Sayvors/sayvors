"""Chart planning for Ask Sayvors.

A small tool-using planner decides whether a visualization helps, queries one
of the fixed business datasets in `chart_data`, and builds chart payloads only
from columns that dataset actually returned. The final answer model then writes
the prose with the chart summaries in view.

No chart is forced: a planner reply with no tool calls means "answer normally".
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.gateway import (
    LLMMessage,
    ToolDefinition,
    ToolParameter,
    complete,
)
from ..users.models import User
from . import memory as chat_memory
from .chart_data import (
    DATASETS,
    catalog_prompt,
    query_dataset,
)

logger = logging.getLogger(__name__)

MAX_PLAN_STEPS = 4
MAX_CHARTS = 3
# A model that rejects the tool schema once is very likely to reject it again;
# skip the wasted round trip for a while and use the JSON planner directly.
TOOL_FAILURE_TTL_SECONDS = 30 * 60
_tool_failures: dict[str, float] = {}

CHART_TYPES = (
    "bar", "line", "area", "stacked_bar", "donut", "pie",
    "ranking", "scatter", "bubble", "heatmap", "radar", "funnel",
    "gauge", "treemap", "histogram", "kpi",
)
NUMERIC_TYPES = {"number", "currency", "percent", "seconds", "rating", "ratio"}
CHART_MAX_ROWS = 60
CATEGORY_MAX_ROWS = 12
HEATMAP_MAX_CELLS = 24 * 7
WEEKDAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def _weekday_sort_key(value: str) -> int:
    try:
        return WEEKDAY_LABELS.index(value)
    except ValueError:
        return len(WEEKDAY_LABELS)


def _hour_sort_key(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 99

# A chart should be considered when the owner asks for a shape, comparison or
# follow-up to a chart they just saw. Plain factual questions skip the planner,
# which keeps ordinary chat fast and avoids forcing a visual onto every answer.
_CHART_HINT_RE = re.compile(
    r"\b(chart|charts|graph|graphs|plot|heatmap|radar|funnel|gauge|"
    r"treemap|bubble|histogram|scatter|visuali[sz]e|visuali[sz]ation|"
    r"trend|trends|over time|by (day|week|month|quarter|year|location|branch|"
    r"platform|channel|category|stage|purpose|source)|breakdown|distribution|"
    r"share|split|compare|comparison|versus|vs|top \d*|highest|lowest|"
    r"ranking|rank|growth|kpi|dashboard|performance|summary|summarize|"
    r"stats|statistics|headline|how (are|is) .* (doing|"
    r"performing)|monthly|weekly|daily)\b",
    re.I,
)
_FOLLOW_UP_RE = re.compile(
    r"\b(this|that|it|same|those|these|now|also|instead|again|by|as a|make it)\b",
    re.I,
)


def wants_chart(message: str, has_chart_memory: bool = False) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    if _CHART_HINT_RE.search(text):
        return True
    # A short follow-up in a chat that already produced a chart ("and by
    # location?", "make it a pie") is chart work even without a keyword.
    return bool(has_chart_memory and len(text) <= 140 and _FOLLOW_UP_RE.search(text))


# A direct instruction to draw something. Only these earn the deterministic
# auto-plan when the model planner returns nothing — a vague "how is my
# performance?" must stay a text answer rather than getting a forced chart.
_EXPLICIT_CHART_RE = re.compile(
    r"\b(charts?|graphs?|plots?|visuali[sz]e|visuali[sz]ation|dashboards?)\b",
    re.I,
)


def explicit_chart_request(message: str) -> bool:
    return bool(_EXPLICIT_CHART_RE.search(message or ""))


def _tools_available(model: str) -> bool:
    failed_at = _tool_failures.get(model)
    if failed_at is None:
        return True
    if time.monotonic() - failed_at > TOOL_FAILURE_TTL_SECONDS:
        _tool_failures.pop(model, None)
        return True
    return False


def _mark_tools_unavailable(model: str) -> None:
    _tool_failures[model] = time.monotonic()


_ARG_ALIASES = {
    "dataset_id": "dataset_id",
    "datasetid": "dataset_id",
    "chart_type": "chart_type",
    "charttype": "chart_type",
    "include_kpis": "include_kpis",
    "includekpis": "include_kpis",
    "x_label": "x",
    "xlabel": "x",
}


def _normalize_args(args: dict) -> dict:
    out: dict = {}
    for key, value in (args or {}).items():
        compact = re.sub(r"[^a-z0-9]+", "", str(key).lower())
        normalized = _ARG_ALIASES.get(compact, key)
        out[normalized] = value
    return out


@dataclass
class ChartPlan:
    charts: list[dict] = field(default_factory=list)
    datasets: dict[str, dict] = field(default_factory=dict)
    steps: list[dict] = field(default_factory=list)
    notes: str = ""


def _tool_definitions() -> list[ToolDefinition]:
    platform_values = [
        "google_reviews", "whatsapp", "instagram", "facebook",
        "x", "telegram", "linkedin",
    ]
    return [
        ToolDefinition(
            name="get_business_data",
            description=(
                "Query one aggregated, tenant-scoped business dataset. Call this "
                "before create_chart. Use the exact dataset keys from the catalog. "
                "The result includes a dataset_id, columns, a small row preview, "
                "KPIs and a recommended chart. If the same metric was already "
                "queried in this chat, reuse its dataset_id instead of querying again."
            ),
            parameters={
                "dataset": ToolParameter(
                    type="string",
                    enum=list(DATASETS.keys()),
                    description="Dataset key from the catalog.",
                ),
                "days": ToolParameter(
                    type="integer",
                    description="Lookback window in days. Use 0 for all time. Default 30.",
                ),
                "platform": ToolParameter(
                    type="string",
                    enum=platform_values,
                    description="Optional platform filter when the dataset supports it.",
                ),
                "location": ToolParameter(
                    type="string",
                    description="Optional location/branch name filter when supported.",
                ),
            },
            required=["dataset"],
        ),
        ToolDefinition(
            name="create_chart",
            description=(
                "Build one chart from a dataset returned by get_business_data. "
                "Never pass values; pass only column names. The server validates "
                "the columns and the chart type against the real rows. Do not "
                "create a chart for an empty dataset or a duplicate of one "
                "already shown in this chat."
            ),
            parameters={
                "dataset_id": ToolParameter(
                    type="string",
                    description="dataset_id returned by get_business_data (current or earlier turn).",
                ),
                "chart_type": ToolParameter(
                    type="string",
                    enum=list(CHART_TYPES),
                    description=(
                        "bar, line, area, stacked_bar, donut/pie, ranking, "
                        "scatter, bubble, heatmap, radar, funnel, gauge, "
                        "treemap, histogram or kpi. Match the data shape: line/"
                        "area for time, bar for comparison, donut for parts of "
                        "a whole, ranking for top lists, stacked_bar for "
                        "composition, scatter/bubble for two metrics, heatmap "
                        "for two dimensions (day × hour), radar for multi-metric "
                        "profiles per location, funnel for ordered stages, "
                        "gauge for one bounded value, treemap for share of a "
                        "total, histogram for a distribution."
                    ),
                ),
                "title": ToolParameter(
                    type="string",
                    description="Short factual title, e.g. 'Review volume · last 30 days'.",
                ),
                "subtitle": ToolParameter(
                    type="string",
                    description="Optional one-line scope note (window, filter).",
                ),
                "x": ToolParameter(
                    type="string",
                    description="Column for the x axis / categories. Defaults to 'label'.",
                ),
                "series": ToolParameter(
                    type="array",
                    items_type="string",
                    description="Numeric column keys to plot. Defaults to the dataset recommendation.",
                ),
                "include_kpis": ToolParameter(
                    type="boolean",
                    description="Show the dataset KPIs above the chart.",
                ),
            },
            required=["dataset_id", "chart_type", "title"],
        ),
    ]


def _planner_prompt(
    memory: dict,
    business_context: str,
    shown_charts: list[dict],
) -> str:
    cached = chat_memory.dataset_summaries(memory)
    previous = [
        {
            "title": c.get("title"),
            "type": c.get("type"),
            "dataset": c.get("dataset"),
        }
        for c in shown_charts[-MAX_CHARTS:]
    ]
    return (
        "You are the chart planner for Sayvors, a business assistant.\n"
        "Decide whether the owner's question benefits from one or more charts. "
        "A chart is useful for trends, distributions, comparisons, rankings, "
        "part-to-whole shares and KPI summaries. Do NOT force a chart for a "
        "single fact, a policy answer, or a question the available data cannot "
        "answer. Never invent values or missing data.\n\n"
        f"BUSINESS CONTEXT:\n{business_context or 'No live business snapshot available.'}\n\n"
        f"DATASET CATALOG:\n{catalog_prompt()}\n\n"
        f"DATASETS ALREADY QUERIED IN THIS CHAT:\n{json.dumps(cached, default=str)[:4000]}\n\n"
        f"CHARTS ALREADY SHOWN IN THIS CHAT:\n{json.dumps(previous, default=str)[:1500]}\n\n"
        "HOW TO WORK:\n"
        "1. Pick the single dataset that answers the question. If it needs a "
        "comparison across two unrelated metrics, you may use two datasets.\n"
        "2. Call get_business_data for a dataset not already cached.\n"
        "3. Call create_chart with that dataset_id and the most appropriate "
        "type. Use only columns that exist in the dataset. Do not repeat a "
        "chart already shown; mention the existing one in your final text instead.\n"
        "4. At most 2 charts unless the owner explicitly asks for more. A KPI "
        "summary is one chart with chart_type='kpi'.\n"
        "5. If the data is empty or the question is not visual, do not call "
        "create_chart. Reply with exactly NO_CHART.\n"
        "6. Pick the chart type that fits the data shape, not a default: heatmap "
        "only for the review_heatmap dataset, radar for sentiment_by_location, "
        "scatter/bubble only when the dataset has two numeric columns.\n"
        "7. Never create a chart whose title or meaning is not supported by the "
        "dataset. Dates are ISO YYYY-MM-DD in the data; do not reformat them.\n"
        "8. Reply in the user's language when writing the final text."
    )


def _dataset_id(query_key: str) -> str:
    return "ds_" + hashlib.sha1(query_key.encode("utf-8")).hexdigest()[:12]


def _numeric_columns(dataset: dict) -> set[str]:
    return {
        str(c.get("key"))
        for c in (dataset.get("columns") or [])
        if str(c.get("type")) in NUMERIC_TYPES and c.get("key") != "label"
    }


def _column_label(dataset: dict, key: str) -> str:
    for col in dataset.get("columns") or []:
        if str(col.get("key")) == key:
            return str(col.get("label") or key)
    return key.replace("_", " ").title()


def _column_format(dataset: dict, key: str) -> str:
    for col in dataset.get("columns") or []:
        if str(col.get("key")) == key:
            kind = str(col.get("type") or "number")
            return kind if kind in NUMERIC_TYPES else "number"
    return "number"


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _resolve_type(requested: str, dataset: dict, x: str, series: list[str]) -> str:
    rows = dataset.get("rows") or []
    requested = requested if requested in CHART_TYPES else "bar"
    if requested == "kpi":
        return "kpi" if dataset.get("kpis") else "bar"
    if not rows or not series:
        return "kpi" if dataset.get("kpis") else "bar"
    # Heatmap rows are pre-shaped by the dataset (x/y/value), so it does not
    # depend on numeric columns the way the axis charts do.
    if requested == "heatmap":
        if dataset.get("heatmap") and any(row.get("value") is not None for row in rows):
            return "heatmap"
        return "bar"
    if requested == "bubble":
        nums = [row.get("size") for row in rows]
        if (
            x and x != "label"
            and len(series) == 1
            and any(isinstance(v, (int, float)) and v > 0 for v in nums)
        ):
            return "bubble"
        return "scatter" if x and x != "label" and len(series) == 1 else "bar"
    if requested == "radar":
        # Radar axes are the metrics (series), one polygon per row/entity.
        # Fewer than three metrics degenerates into a line, so fall back.
        return "radar" if len(series) >= 3 and len(rows) >= 1 else "bar"
    if requested == "funnel":
        return "funnel" if len(series) == 1 and len(rows) >= 2 else "bar"
    if requested == "gauge":
        return "gauge" if dataset.get("gauge_max") or len(rows) == 1 else "bar"
    if requested == "treemap":
        if len(series) == 1 and all(
            isinstance(row.get(series[0]), (int, float)) and float(row.get(series[0]) or 0) > 0
            for row in rows
        ):
            return "treemap"
        return "bar"
    if requested in ("donut", "pie"):
        if len(series) != 1:
            return "bar"
        values = [row.get(series[0]) for row in rows]
        if not all(isinstance(v, (int, float)) and v >= 0 for v in values):
            return "bar"
        if sum(float(v or 0) for v in values) <= 0:
            return "bar"
        return requested
    if requested in ("line", "area"):
        if len(rows) < 2:
            return "bar"
        return requested
    if requested == "stacked_bar":
        return "stacked_bar" if len(series) >= 2 else "bar"
    if requested == "scatter":
        return "scatter" if x and x != "label" and len(series) == 1 else "line"
    if requested in ("ranking", "histogram"):
        # A histogram is a bar over a numeric distribution; the renderer can
        # treat it as bars with no gaps between categories.
        return requested if len(series) == 1 else "bar"
    return "bar"


def _limit_categories(rows: list[dict], series: list[str]) -> list[dict]:
    if len(rows) <= CATEGORY_MAX_ROWS:
        return rows
    head = rows[: CATEGORY_MAX_ROWS - 1]
    rest = rows[CATEGORY_MAX_ROWS - 1:]
    other = {"label": "Other"}
    for key in series:
        other[key] = round(sum(float(row.get(key) or 0) for row in rest), 2)
    return head + [other]


def _build_chart(
    dataset: dict,
    *,
    chart_type: str,
    title: str,
    subtitle: str | None,
    x: str | None,
    series: list[str] | None,
    include_kpis: bool,
) -> dict:
    rows = list(dataset.get("rows") or [])
    numeric = _numeric_columns(dataset)
    x = (x or dataset.get("suggested_x") or "label").strip()
    requested_series = [s for s in (series or dataset.get("suggested_series") or []) if s]
    requested_series = [s for s in requested_series if s in numeric]
    if not requested_series:
        requested_series = [s for s in (dataset.get("suggested_series") or []) if s in numeric]
    if not requested_series:
        # Fall back to the first numeric column, never a fabricated series.
        first = next(iter(numeric), None)
        if first:
            requested_series = [first]
    if not rows:
        raise ValueError("That dataset returned no rows, so there is nothing to chart.")
    if not requested_series:
        raise ValueError("That dataset has no numeric column to plot.")

    final_type = _resolve_type(chart_type, dataset, x, requested_series)
    if final_type not in ("kpi", "heatmap") and x not in {"label", *numeric}:
        x = dataset.get("suggested_x") or "label"

    chart_rows: list[dict]
    if final_type == "heatmap":
        chart_rows = [
            {
                "label": str(row.get("label") or ""),
                "x": str(row.get("x") or ""),
                "y": str(row.get("y") or ""),
                "value": float(row.get("value") or 0),
            }
            for row in rows
            if row.get("x") not in (None, "") and row.get("y") not in (None, "")
        ][:HEATMAP_MAX_CELLS]
    elif final_type == "bubble":
        x_key = x if x != "label" else requested_series[0]
        y_key = requested_series[0]
        chart_rows = [
            {
                "label": str(row.get("label") or ""),
                "x": row.get(x_key),
                "y": row.get(y_key),
                "size": row.get("size"),
            }
            for row in rows
            if isinstance(row.get(x_key), (int, float))
            and isinstance(row.get(y_key), (int, float))
            and isinstance(row.get("size"), (int, float))
        ][:CHART_MAX_ROWS]
        if len(chart_rows) < 2:
            raise ValueError("Bubble needs at least two points with x, y and size.")
    elif final_type == "scatter":
        x_key = x if x != "label" else requested_series[0]
        y_key = requested_series[0]
        if x_key == y_key:
            raise ValueError("Scatter needs two different numeric columns.")
        chart_rows = [
            {"label": str(row.get("label") or ""), "x": row.get(x_key), "y": row.get(y_key)}
            for row in rows
            if isinstance(row.get(x_key), (int, float)) and isinstance(row.get(y_key), (int, float))
        ][:CHART_MAX_ROWS]
        if len(chart_rows) < 2:
            final_type = "bar"
            chart_rows = [
                {"label": str(row.get("label") or ""), **{s: row.get(s) for s in requested_series}}
                for row in rows
            ]
    elif final_type == "radar":
        chart_rows = [
            {"label": str(row.get("label") or ""), **{s: row.get(s) for s in requested_series}}
            for row in rows
        ][:CATEGORY_MAX_ROWS]
    elif final_type in ("line", "area"):
        chart_rows = [
            {"label": str(row.get("label") or ""), **{s: row.get(s) for s in requested_series}}
            for row in rows
        ][:CHART_MAX_ROWS]
    elif final_type in ("donut", "pie"):
        chart_rows = [
            {"label": str(row.get("label") or ""), requested_series[0]: row.get(requested_series[0])}
            for row in rows
        ]
        chart_rows = _limit_categories(chart_rows, requested_series)
    elif final_type == "funnel":
        chart_rows = [
            {"label": str(row.get("label") or ""), requested_series[0]: row.get(requested_series[0])}
            for row in rows
        ][:8]
    elif final_type == "gauge":
        chart_rows = [
            {"label": str(row.get("label") or "Value"), requested_series[0]: row.get(requested_series[0])}
            for row in rows[:1]
        ]
    elif final_type == "treemap":
        chart_rows = [
            {"label": str(row.get("label") or ""), requested_series[0]: row.get(requested_series[0])}
            for row in rows
        ]
        chart_rows = _limit_categories(chart_rows, requested_series)
    elif final_type == "ranking":
        chart_rows = [
            {"label": str(row.get("label") or ""), requested_series[0]: row.get(requested_series[0])}
            for row in rows
        ]
        chart_rows.sort(key=lambda r: float(r.get(requested_series[0]) or 0), reverse=True)
        chart_rows = chart_rows[:10]
    elif final_type == "histogram":
        chart_rows = [
            {"label": str(row.get("label") or ""), **{s: row.get(s) for s in requested_series}}
            for row in rows
        ]
        chart_rows = _limit_categories(chart_rows, requested_series)
    else:  # bar / stacked_bar
        chart_rows = [
            {"label": str(row.get("label") or ""), **{s: row.get(s) for s in requested_series}}
            for row in rows
        ]
        chart_rows = _limit_categories(chart_rows, requested_series)

    kpis = []
    if include_kpis or final_type == "kpi":
        kpis = [
            k for k in (dataset.get("kpis") or [])
            if k.get("value") is not None
        ][:4]
    signature = "|".join([
        str(dataset.get("query_key") or ""),
        final_type,
        x,
        ",".join(requested_series),
    ])
    domain = str(dataset.get("domain") or "")
    chart = {
        "id": "chart_" + hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12],
        "type": final_type,
        "title": _clean_text(title, 90),
        "subtitle": _clean_text(subtitle, 160) if subtitle else None,
        "dataset": dataset.get("dataset"),
        "domain": domain,
        "x_label": _column_label(dataset, x) if final_type != "heatmap" else "Hour",
        "y_label": "Day" if final_type == "heatmap" else None,
        "series": [
            {
                "key": s,
                "label": _column_label(dataset, s),
                "format": _column_format(dataset, s),
            }
            for s in requested_series
        ] if final_type not in ("kpi", "heatmap") else (
            [{"key": "value", "label": "Reviews", "format": "number"}]
            if final_type == "heatmap" else []
        ),
        "rows": chart_rows,
        "kpis": kpis,
        "window_days": dataset.get("window_days"),
        "signature": signature,
    }
    if final_type == "heatmap":
        chart["x_values"] = sorted({row["x"] for row in chart_rows}, key=_hour_sort_key)
        chart["y_values"] = sorted({row["y"] for row in chart_rows}, key=_weekday_sort_key)
    if final_type == "gauge":
        chart["max_value"] = dataset.get("gauge_max") or None
    if final_type == "kpi":
        chart["rows"] = []
        chart["series"] = []
    return chart


async def _get_data(
    db: AsyncSession,
    tenant_id: str,
    args: dict,
    context: dict,
    memory: dict,
    steps: list[dict],
    on_step=None,
) -> dict:
    dataset_key = str(args.get("dataset") or "")
    if dataset_key not in DATASETS:
        return {"error": "Unknown dataset. Use a key from the catalog."}
    platform = str(args.get("platform") or "") or None
    location = str(args.get("location") or "") or None
    raw_days = args.get("days")
    try:
        # 0 means all time and must survive — `0 or 30` silently rewrote it.
        days = 30 if raw_days in (None, "") else int(raw_days)
    except (TypeError, ValueError):
        days = 30
    query_key = f"{dataset_key}|{days}|{platform or ''}|{location or ''}"
    existing = context.get(query_key)
    if existing:
        return _dataset_observation(existing, reused=True)
    cached = chat_memory.recall_dataset(memory, query_key)
    if cached:
        context[query_key] = cached
        step = {
            "id": f"chart-data:{dataset_key}",
            "label": f"Reusing your {DATASETS[dataset_key].label.lower()} data",
            "detail": "already loaded in this chat",
        }
        steps.append(step)
        if on_step is not None:
            try:
                on_step(step)
            except Exception:
                pass
        return _dataset_observation(cached, reused=True)

    result = await query_dataset(
        db, tenant_id, dataset_key, days=days, platform=platform, location=location
    )
    result["dataset_id"] = _dataset_id(query_key)
    result["rows"] = list(result.get("rows") or [])
    if result["rows"]:
        chat_memory.remember_dataset(memory, result)
    context[query_key] = result
    step = {
        "id": f"chart-data:{dataset_key}",
        "label": f"Reading your {DATASETS[dataset_key].label.lower()}",
        "detail": f"{len(result['rows'])} rows",
    }
    steps.append(step)
    if on_step is not None:
        try:
            on_step(step)
        except Exception:
            pass
    return _dataset_observation(result, reused=False)


def _dataset_observation(dataset: dict, *, reused: bool) -> dict:
    rows = list(dataset.get("rows") or [])
    return {
        "dataset_id": dataset.get("dataset_id"),
        "dataset": dataset.get("dataset"),
        "title": dataset.get("title"),
        "query_key": dataset.get("query_key"),
        "window_days": dataset.get("window_days"),
        "columns": dataset.get("columns"),
        "row_count": len(rows),
        "rows_preview": rows[:8],
        "kpis": dataset.get("kpis"),
        "suggested_type": dataset.get("suggested_type"),
        "suggested_x": dataset.get("suggested_x"),
        "suggested_series": dataset.get("suggested_series"),
        "note": dataset.get("note"),
        "reused": reused,
    }


def _create_chart(
    args: dict,
    context: dict,
    memory: dict,
    charts: list[dict],
    signatures: set[str],
) -> dict:
    dataset_id = str(args.get("dataset_id") or "")
    dataset = None
    for candidate in context.values():
        if candidate.get("dataset_id") == dataset_id:
            dataset = candidate
            break
    if dataset is None:
        dataset = (memory.get("datasets") or {}).get(dataset_id)
    if dataset is None:
        return {"error": "Unknown dataset_id. Call get_business_data first."}
    if len(charts) >= MAX_CHARTS:
        return {"error": f"At most {MAX_CHARTS} charts per answer."}

    chart_type = str(args.get("chart_type") or "bar")
    title = _clean_text(args.get("title"), 90)
    if not title:
        return {"error": "A factual chart title is required."}
    try:
        chart = _build_chart(
            dataset,
            chart_type=chart_type,
            title=title,
            subtitle=args.get("subtitle"),
            x=args.get("x"),
            series=args.get("series"),
            include_kpis=bool(args.get("include_kpis", False)),
        )
    except ValueError as e:
        return {"error": str(e)}
    signature = chart["signature"]
    if signature in signatures:
        return {"error": "That chart is already shown in this conversation."}
    signatures.add(signature)
    charts.append(chart)
    chat_memory.remember_chart(memory, chart)
    return {
        "created": True,
        "chart_id": chart["id"],
        "type": chart["type"],
        "title": chart["title"],
        "series": [s["label"] for s in chart["series"]],
        "points": len(chart["rows"]),
    }


def _json_planner_prompt(memory: dict, business_context: str) -> str:
    cached = chat_memory.dataset_summaries(memory)
    return (
        "You are the chart planner for Sayvors. Choose charts only when the "
        "owner's question is visual (trend, comparison, distribution, ranking, "
        "share, summary). Never invent values.\n"
        f"BUSINESS CONTEXT:\n{business_context}\n\n"
        f"DATASET CATALOG:\n{catalog_prompt()}\n\n"
        f"DATASETS ALREADY QUERIED (reuse dataset_id when possible):\n"
        f"{json.dumps(cached, default=str)[:4000]}\n\n"
        "Return ONLY a JSON object, no markdown and no prose, in this shape:\n"
        '{"charts":[{"dataset":"review_volume","days":30,"platform":null,'
        '"location":null,"type":"line","title":"Reviews over time",'
        '"subtitle":"Last 30 days","series":["reviews"],"include_kpis":true}]}\n\n'
        "Rules:\n"
        "- Use one of the dataset keys exactly as listed.\n"
        "- Use type one of: bar, line, area, stacked_bar, donut, pie, ranking, "
        "scatter, bubble, heatmap, radar, funnel, gauge, treemap, histogram, kpi.\n"
        "- Omit series when you do not know the columns; the server uses the "
        "dataset's recommended numeric series.\n"
        "- days: 7, 30, 90, 180 or 365; use 0 for all time.\n"
        "- At most 2 charts. If the question is not visual, return {\"charts\":[]}.\n"
        "- If the data is empty, return {\"charts\":[]} rather than a fake chart."
    )


def _parse_json_object(text: str) -> dict | None:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


async def _json_chart_fallback(
    *,
    db: AsyncSession,
    tenant_id: str,
    model: str,
    message: str,
    history: list[LLMMessage],
    memory: dict,
    business_context: str,
    plan: ChartPlan,
    context: dict[str, dict],
    signatures: set[str],
    on_step=None,
) -> None:
    """Tool-free plan for providers that mangle function calls.

    Groq/qwen can emit `<function=create chart>` and fail validation before
    the call ever reaches us. A second, tools-disabled call still lets the
    owner get a chart from the same fixed catalog.
    """
    try:
        resp = await complete(
            model=model,
            messages=[*history[-6:], LLMMessage(role="user", content=message)],
            system_prompt=_json_planner_prompt(memory, business_context),
            temperature=0.1,
            max_tokens=650,
            tenant_id=tenant_id,
            purpose="assistant.chart_plan",
        )
    except Exception as e:
        logger.warning("Assistant JSON chart fallback unavailable: %s", e)
        return
    data = _parse_json_object(resp.content)
    if not data:
        plan.notes = _clean_text(resp.content, 300)
        return
    items = data.get("charts")
    if not isinstance(items, list):
        return
    for item in items[:MAX_CHARTS]:
        if not isinstance(item, dict):
            continue
        item = _normalize_args(item)
        dataset_key = str(item.get("dataset") or "")
        if dataset_key not in DATASETS:
            continue
        days = item.get("days", 30)
        try:
            days = int(days)
        except (TypeError, ValueError):
            days = 30
        platform = str(item.get("platform") or "") or None
        location = str(item.get("location") or "") or None
        obs = await _get_data(
            db, tenant_id,
            {"dataset": dataset_key, "days": days,
             "platform": platform, "location": location},
            context, memory, plan.steps, on_step,
        )
        if not obs.get("row_count"):
            continue
        series = item.get("series")
        args = {
            "dataset_id": obs.get("dataset_id"),
            "chart_type": str(item.get("type") or "bar"),
            "title": item.get("title") or DATASETS[dataset_key].label,
            "subtitle": item.get("subtitle"),
            "series": series if isinstance(series, list) else None,
            "include_kpis": bool(item.get("include_kpis", True)),
        }
        created = _create_chart(args, context, memory, plan.charts, signatures)
        if created.get("created"):
            step = {
                "id": f"chart:{created['chart_id']}",
                "label": f"Chart ready: {created['title']}",
                "detail": created["type"].replace("_", " "),
            }
            plan.steps.append(step)
            if on_step is not None:
                try:
                    on_step(step)
                except Exception:
                    pass


_AUTO_INTENTS: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (re.compile(r"\brating|\bstars?\b", re.I), ("rating_distribution",)),
    (re.compile(r"\bsentiment|positive|negative\b", re.I), ("sentiment_distribution",)),
    (re.compile(r"\blocations?|branches?\b", re.I), ("reviews_by_location",)),
    (re.compile(r"\brepl(?:y|ies|ied|ying)|responses?\b", re.I), ("reply_status",)),
    (
        re.compile(r"\bvisib|impressions?|search|maps|discover", re.I),
        ("google_visibility",),
    ),
    (re.compile(r"\btopics?|mentions?|complain", re.I), ("review_topics",)),
    (
        re.compile(r"\bvolume|trend|over time|growth|monthly|weekly|daily", re.I),
        ("review_volume",),
    ),
    (
        re.compile(r"\bwhen|busiest|time of day|hours?|heatmap", re.I),
        ("review_heatmap",),
    ),
]

# What "make me charts" means with no more specific intent: the three datasets
# that describe this product's core data (ratings, branches, review flow).
_AUTO_DEFAULT_DATASETS: tuple[str, ...] = (
    "rating_distribution",
    "reviews_by_location",
    "review_volume",
)


def _auto_dataset_keys(message: str) -> list[str]:
    """Deterministic dataset choice for an explicit chart request.

    Only used after the model planner produced nothing, so the owner still
    gets a real chart from real rows instead of a text-drawn bar chart.
    """
    text = message or ""
    keys: list[str] = []
    for pattern, datasets in _AUTO_INTENTS:
        if pattern.search(text):
            keys.extend(datasets)
    for key in _AUTO_DEFAULT_DATASETS:
        if key not in keys:
            keys.append(key)
    return keys


async def _auto_chart_plan(
    *,
    db: AsyncSession,
    tenant_id: str,
    message: str,
    memory: dict,
    plan: ChartPlan,
    context: dict[str, dict],
    signatures: set[str],
    on_step=None,
) -> None:
    """Build charts straight from the catalog when the planner returned none.

    The owner asked for a visual; every value here comes from the same fixed,
    tenant-scoped datasets the planner uses, so this is a deterministic plan,
    not a fabricated one.
    """
    for dataset_key in _auto_dataset_keys(message):
        if len(plan.charts) >= MAX_CHARTS:
            break
        spec = DATASETS.get(dataset_key)
        if spec is None:
            continue
        try:
            obs = await _get_data(
                db,
                tenant_id,
                {"dataset": dataset_key, "days": 0},
                context,
                memory,
                plan.steps,
                on_step,
            )
        except Exception as e:
            logger.warning("Auto chart dataset %s failed: %s", dataset_key, e)
            continue
        if not obs.get("row_count"):
            continue
        created = _create_chart(
            {
                "dataset_id": obs.get("dataset_id"),
                "chart_type": obs.get("suggested_type") or spec.suggested_type,
                "title": obs.get("title") or spec.label,
                "subtitle": "All synced data",
                "series": obs.get("suggested_series"),
                "include_kpis": True,
            },
            context,
            memory,
            plan.charts,
            signatures,
        )
        if created.get("created"):
            step = {
                "id": f"chart:{created['chart_id']}",
                "label": f"Chart ready: {created['title']}",
                "detail": created["type"].replace("_", " "),
            }
            plan.steps.append(step)
            if on_step is not None:
                try:
                    on_step(step)
                except Exception:
                    pass
    if not plan.charts:
        plan.notes = "No chartable rows yet."


async def plan_charts(
    *,
    db: AsyncSession,
    user: User,
    tenant_id: str,
    model: str,
    message: str,
    history: list[LLMMessage],
    memory: dict,
    business_context: str = "",
    on_step=None,
) -> ChartPlan:
    """Run the tool-using planner. Never raises; chart work is optional."""
    plan = ChartPlan()
    if not wants_chart(message, bool(memory.get("charts"))):
        return plan

    signatures = chat_memory.chart_signatures(memory)
    context: dict[str, dict] = {}
    shown = list(memory.get("charts") or [])
    if not _tools_available(model):
        await _json_chart_fallback(
            db=db, tenant_id=tenant_id, model=model, message=message,
            history=history, memory=memory, business_context=business_context,
            plan=plan, context=context, signatures=signatures, on_step=on_step,
        )
        plan.datasets = context
        return plan
    messages = [
        *history[-8:],
        LLMMessage(role="user", content=message),
    ]
    tools = _tool_definitions()
    system = _planner_prompt(memory, business_context, shown)
    provider_error = False
    tool_schema_error = False
    called_tools = False
    started = time.monotonic()

    for _ in range(MAX_PLAN_STEPS):
        if time.monotonic() - started > 20:
            provider_error = True
            plan.notes = "planner timed out"
            break
        try:
            resp = await complete(
                model=model,
                messages=list(messages),
                system_prompt=system,
                temperature=0.1,
                max_tokens=700,
                tools=tools,
                tenant_id=tenant_id,
                purpose="assistant.chart_plan",
            )
        except Exception as e:
            # Some OpenAI-compatible models emit a malformed function name and
            # Groq rejects the whole request before we see a ToolCall. Only a
            # tool-schema reject earns the tools-disabled JSON plan — a slow or
            # rate-limited provider would just fail the second call too and
            # double the wait, so it answers in text instead.
            logger.warning("Assistant chart planner unavailable: %s", e)
            provider_error = True
            msg = str(e).lower()
            if (
                "tool" in msg
                or "function" in msg
                or "validation" in msg
                or "400" in msg
            ):
                tool_schema_error = True
                _mark_tools_unavailable(model)
            plan.notes = "planner unavailable"
            break
        if not resp.tool_calls:
            plan.notes = _clean_text(resp.content, 400)
            break
        called_tools = True

        observations: list[str] = []
        for call in resp.tool_calls:
            name = re.sub(r"[^a-z0-9]+", "_", (call.name or "").strip().lower()).strip("_")
            if name in ("createchart", "make_chart", "makechart", "chart"):
                name = "create_chart"
            elif name in ("getdata", "get_data", "business_data", "get_business_data"):
                name = "get_business_data"
            if name == "get_business_data":
                obs = await _get_data(
                    db, tenant_id, _normalize_args(call.arguments or {}),
                    context, memory, plan.steps, on_step,
                )
            elif name == "create_chart":
                obs = _create_chart(
                    _normalize_args(call.arguments or {}), context, memory,
                    plan.charts, signatures,
                )
                if obs.get("created"):
                    step = {
                        "id": f"chart:{obs['chart_id']}",
                        "label": f"Chart ready: {obs['title']}",
                        "detail": obs["type"].replace("_", " "),
                    }
                    plan.steps.append(step)
                    if on_step is not None:
                        try:
                            on_step(step)
                        except Exception:
                            pass
            else:
                obs = {"error": f"unknown tool: {call.name}"}
            observations.append(f"Tool {call.name} returned:\n{json.dumps(obs, default=str)[:6000]}")
        messages.append(LLMMessage(
            role="assistant",
            content=(resp.content or "") + f"\n[called {len(resp.tool_calls)} chart tool(s)]",
        ))
        messages.append(LLMMessage(role="user", content="\n\n".join(observations)))

    has_rows = any(bool(ds.get("rows")) for ds in context.values())
    notes = (plan.notes or "").strip().upper()
    if not plan.charts:
        if tool_schema_error or (not provider_error and (has_rows or (not context and notes != "NO_CHART"))):
            await _json_chart_fallback(
                db=db, tenant_id=tenant_id, model=model, message=message,
                history=history, memory=memory, business_context=business_context,
                plan=plan, context=context, signatures=signatures, on_step=on_step,
            )
        elif called_tools and not has_rows:
            plan.notes = "The business data has no rows for that chart yet."

    # The owner explicitly asked for a chart, so an empty plan is a failure —
    # not a "nothing to show". Build from the fixed catalog with real rows
    # instead of letting the answer model draw ASCII bars.
    if not plan.charts and explicit_chart_request(message):
        await _auto_chart_plan(
            db=db,
            tenant_id=tenant_id,
            message=message,
            memory=memory,
            plan=plan,
            context=context,
            signatures=signatures,
            on_step=on_step,
        )

    plan.datasets = context
    return plan


def chart_summary_for_prompt(charts: list[dict]) -> str:
    if not charts:
        return ""
    lines = []
    for chart in charts[:MAX_CHARTS]:
        kpis = ", ".join(
            f"{k.get('label')}: {k.get('value')}" for k in (chart.get("kpis") or [])[:3]
        )
        stats = []
        rows = chart.get("rows") or []
        for series in (chart.get("series") or [])[:4]:
            values = [
                float(row.get(series.get("key")))
                for row in rows
                if isinstance(row.get(series.get("key")), (int, float))
            ]
            if not values:
                continue
            latest = values[-1]
            stats.append(
                f"{series.get('label')}: total={round(sum(values), 2)}, "
                f"latest={round(latest, 2)}, min={round(min(values), 2)}, "
                f"max={round(max(values), 2)}"
            )
        lines.append(
            f"- {chart.get('title')} ({chart.get('type')}, {chart.get('domain')}"
            + (f"; {kpis}" if kpis else "")
            + (f"; {'; '.join(stats)}" if stats else "")
            + ")"
        )
    return "\n".join(lines)
