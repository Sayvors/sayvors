# Ask Sayvors charts

Implemented 2026-11-05.

## What it does

Ask Sayvors can answer a visual question with one or more charts rendered
inside the chat. The chart planner runs only for questions that look visual
(trend, comparison, distribution, ranking, share, summary, explicit "chart"),
so a plain factual question never gets a decorative chart.

The flow is:

1. The planner receives the user question, the recent conversation, the
   business summary, datasets already queried in this chat, and charts already
   shown.
2. It chooses a catalog dataset and calls `get_business_data` (or reuses a
   cached `dataset_id`).
3. It calls `create_chart` with column names only. The server validates the
   columns against the real rows and builds the final payload.
4. The SSE stream emits `{"type":"chart","chart":{...}}` events before the
   answer text. The frontend renders them with `ChatChart`.
5. The answer model receives a compact chart summary (title, type, KPIs and
   series totals) and writes prose that references the charts without
   inventing numbers.

## Safety rules

- **No fabricated data.** `create_chart` accepts only a dataset returned in
  this request or in the conversation memory. Unknown series/columns are
  discarded and replaced with the dataset recommendation.
- **No forced charts.** No tool calls means no chart. An empty dataset means no
  chart.
- **No duplicates.** Charts are deduped by
  `query_key + type + x + series` across the conversation.
- **Bounded.** At most 3 charts per answer; rows are capped before rendering.
- **Tenant scoped.** Every dataset query filters by tenant (and channel where
  applicable).
- **No provider/model leakage.** AI usage datasets expose purpose and cost,
  never provider model ids.

## Chart contract

The payload shared by the backend and `apps/web/lib/chat-charts.ts`:

```json
{
  "id": "chart_...",
  "type": "bar | line | area | stacked_bar | donut | pie | ranking | scatter | kpi",
  "title": "Reviews over time",
  "subtitle": "Last 30 days",
  "dataset": "review_volume",
  "domain": "reviews",
  "x_label": "Date",
  "series": [{ "key": "reviews", "label": "Reviews", "format": "number" }],
  "rows": [{ "label": "2026-11-01", "reviews": 4 }],
  "kpis": [{ "label": "Reviews", "value": 44, "format": "number", "delta": null }],
  "window_days": 30
}
```

`format` is one of `number`, `currency`, `percent`, `rating`, `seconds`,
`ratio`, `text`. Scatter rows carry numeric `x` and `y` instead of a series
value map.

## Dataset catalog

`services/api/app/modules/assistant/chart_data.py` owns the fixed datasets:

| Domain | Datasets |
| --- | --- |
| Reviews | review volume, rating distribution, sentiment, reviews by location, reviewer topics, reply status |
| Customers | customer growth, customers by platform, categories, most active customers |
| WhatsApp / messaging | message volume (daily rollups with a raw-message fallback), first response time |
| Sales | lead pipeline, lead categories, lead growth |
| Social | publishing outcomes, post activity, followers |
| Marketing | Google visibility |
| AI | spend by purpose, spend over time |

Distributions that are meaningful across all history automatically retry with
an all-time window when the requested short window is empty, and label that in
the tool observation.

## Conversation memory

`services/api/app/modules/assistant/memory.py` stores a bounded session in
Redis (24h TTL), with an in-process fallback:

- the last 20 turns,
- the last 8 datasets (aggregated rows only),
- chart signatures already shown.

The browser sends the chat id as `session_id`. The server prefers the longer of
the client history and the stored history. A follow-up such as "show that by
location" can reuse the previous dataset or query a different one, and a
repeated chart is skipped rather than duplicated.

## Frontend renderer

`apps/web/components/chat/ChatChart.tsx` is an SVG renderer with no runtime
chart dependency:

- line, area, grouped bar and stacked bar with hover tooltips;
- donut with hover-to-inspect segments and a legend;
- horizontal ranking bars;
- scatter with numeric x/y ticks;
- KPI cards;
- clickable legends that hide series;
- responsive viewBox sizing inside the 400px chat sidebar and full-width
  mobile chat.

Charts are saved with the assistant message in the existing local chat session,
so reopening a conversation restores the visual history.

## Resilience

OpenAI-compatible providers now receive tool definitions and return parsed
`ToolCall`s. Some models still emit malformed tool names (for example
`createChart`) and the provider rejects the whole request. In that case the
planner falls back to a tools-disabled strict-JSON plan, executes the same
server-side datasets, and still renders real charts. The failed model is marked
for 30 minutes so the next chart question goes straight to the JSON path.
