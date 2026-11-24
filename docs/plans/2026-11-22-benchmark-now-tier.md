# Benchmark "Now Tier" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the four "Now" items from the readiness benchmark plan — trend charts, north-star card, distribution strip, own-locations scorecards — on the existing `/api/v1/benchmark/compare` + `/history` endpoints with no new dependencies.

**Architecture:** Two pure server-side helpers (`summary` ranking, `distribution` spread) are computed from the already-loaded subject records and attached additively to the `/compare` response. The frontend renders them with three new inline-SVG/HTML components plus one scorecard grid, all fed by the existing TanStack Query hooks. Pure functions live in a new module so `compare.py` stops growing.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js/React + TanStack Query (frontend), inline SVG (no chart lib), pytest.

**Scope note (per writing-plans scope check):** P0 (named competitor set, gap matrix, sentiment/velocity bars), P1, P2 stay out of this plan — each is its own follow-up plan. This plan produces working, testable software on its own.

---

## File Structure

| File | Responsibility |
| --- | --- |
| Create `services/api/app/modules/benchmark/summary.py` | Pure functions: `distribution(subjects)`, `north_star(subjects, own_keys)` over subject records. No DB, no I/O. |
| Modify `services/api/app/modules/benchmark/router.py` | `/compare` handler attaches `summary` + `distribution` to the cached payload. |
| Create `services/api/tests/test_benchmark_summary.py` | Unit tests for both pure functions (no DB). |
| Create `apps/web/components/benchmark/TrendChart.tsx` | Inline-SVG multi-line chart from `/history` points (rating + reviews/month), question-as-title. |
| Create `apps/web/components/benchmark/NorthStarCard.tsx` | Rank "X of Y", gap-to-leader list, health pill, fix-first CTA. |
| Create `apps/web/components/benchmark/DistributionStrip.tsx` | Best/Median/Worst/Gap bars per metric. |
| Create `apps/web/components/benchmark/OwnScorecards.tsx` | Per own-branch card: rating, velocity, five-star share, top problem, variance flag. |
| Modify `apps/web/app/dashboard/benchmark/compare/page.tsx` | Render the four components above the existing matrix. |
| Modify `apps/web/lib/api-benchmark.ts` | Types for `summary`/`distribution` in the compare response. |
| Modify `apps/web/lib/i18n/en.ts`, `ar.ts` | Copy for the new UI. |

---

### Task 1: Distribution + north-star pure functions (backend, TDD)

**Files:**
- Create: `services/api/app/modules/benchmark/summary.py`
- Test: `services/api/tests/test_benchmark_summary.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for benchmark summary/distribution helpers (pure, no DB)."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.modules.benchmark.summary import distribution, north_star


def _subject(key, name, *, avg=None, month=None, total=None, pos=None,
             five=None, year=None, kind="saved", available=True):
    return {
        "key": key, "kind": kind, "id": key.split(":", 1)[-1],
        "available": available, "name": name,
        "metrics": {
            "avg_rating": avg, "reviews_last_month": month,
            "reviews_last_year": year, "total_reviews": total,
            "total_ratings": total, "five_star": five,
        },
        "facts": {"positive_pct": pos, "top_problems": []},
    }


def test_distribution_best_median_worst_and_gap():
    rows = distribution([
        _subject("saved:a", "Alpha", avg=4.8, month=12, total=200, pos=90),
        _subject("saved:b", "Beta", avg=4.0, month=6, total=100, pos=70),
        _subject("saved:c", "Gamma", avg=3.2, month=2, total=40, pos=40),
    ])
    rating = rows["avg_rating"]
    assert rating["best"]["name"] == "Alpha" and rating["best"]["value"] == 4.8
    assert rating["median"] == 4.0
    assert rating["worst"]["name"] == "Gamma" and rating["worst"]["value"] == 3.2
    assert rating["gap"] == 1.6


def test_distribution_skips_unavailable_and_null_metrics():
    rows = distribution([
        _subject("saved:a", "Alpha", avg=4.5, month=10),
        _subject("saved:x", "Dead", available=False, avg=None),
        _subject("saved:b", "Beta", avg=None, month=4),  # avg missing → excluded
    ])
    assert set(rows["avg_rating"]["values"]) == {4.5}
    assert rows["avg_rating"]["gap"] == 0
    assert "positive_pct" not in rows  # no subject carried it


def test_velocity_uses_month_then_year_fallback():
    rows = distribution([
        _subject("saved:a", "Alpha", month=None, year=120, avg=4.0),
        _subject("saved:b", "Beta", month=6, avg=4.0),
    ])
    assert rows["reviews_per_month"]["best"]["value"] == 10  # 120 / 12


def test_north_star_ranks_own_subject_with_gaps():
    out = north_star(
        [
            _subject("saved:a", "Alpha", avg=4.9, month=20, pos=95),
            _subject("own:c1", "Mine", avg=4.2, month=5, pos=60, kind="own"),
            _subject("saved:b", "Beta", avg=3.8, month=9, pos=80),
        ],
        own_keys=["own:c1"],
    )
    assert out["rank"] == 2 and out["of"] == 3
    assert out["leader"]["name"] == "Alpha"
    assert out["gaps"]["avg_rating"] == 0.7
    assert out["gaps"]["reviews_per_month"] == 15
    assert out["health"] == "warn"


def test_north_star_none_without_own_subject():
    assert north_star([_subject("saved:a", "Alpha", avg=4.0)], own_keys=[]) is None


def test_health_buckets():
    from app.modules.benchmark.summary import health_of
    assert health_of(_subject("s", "A", avg=4.5, pos=85)) == "good"
    assert health_of(_subject("s", "A", avg=3.6, pos=60)) == "warn"
    assert health_of(_subject("s", "A", avg=2.9, pos=30)) == "bad"
    assert health_of(_subject("s", "A", avg=None, pos=None)) == "warn"  # unknown → not good
```

- [ ] **Step 2: Run** `cd services/api; python -m pytest tests/test_benchmark_summary.py -q -n 0` — expect FAIL (`ModuleNotFoundError: app.modules.benchmark.summary`)

- [ ] **Step 3: Implement `summary.py`**

```python
"""North-star ranking + metric distribution over compare subjects.

Pure functions over the records ``compare_subjects`` returns — no DB, no
I/O — so the ranking logic stays unit-testable and ``compare.py`` stops
growing. The compare router calls these after loading subjects and attaches
the results to the cached response.
"""
from __future__ import annotations

from statistics import median
from typing import Any

# The four headline metrics the compare page opens with. ``max`` powers the
# distribution bar scaling (None = scale to the observed best).
METRIC_SPECS: dict[str, dict[str, Any]] = {
    "avg_rating": {"higher_is_better": True, "max": 5.0},
    "reviews_per_month": {"higher_is_better": True, "max": None},
    "total_reviews": {"higher_is_better": True, "max": None},
    "positive_pct": {"higher_is_better": True, "max": 100.0},
}

_HEALTH_BAD_RATING = 3.5
_HEALTH_WARN_RATING = 4.3
_HEALTH_BAD_POSITIVE = 50.0
_HEALTH_WARN_POSITIVE = 75.0


def velocity_per_month(subject: dict[str, Any]) -> float | None:
    """Reviews/month: the 30-day window when present, else year ÷ 12."""
    metrics = subject.get("metrics") or {}
    month = metrics.get("reviews_last_month")
    if month is not None:
        return float(month)
    year = metrics.get("reviews_last_year")
    if year is not None:
        return round(float(year) / 12.0, 1)
    return None


def _value(subject: dict[str, Any], metric: str) -> float | None:
    if metric == "reviews_per_month":
        return velocity_per_month(subject)
    value = (subject.get("metrics") or {}).get(metric)
    if value is None and metric == "total_reviews":
        value = (subject.get("metrics") or {}).get("total_ratings")
    return float(value) if value is not None else None


def health_of(subject: dict[str, Any]) -> str:
    """good / warn / bad — worst bucket across rating and sentiment."""
    rating = _value(subject, "avg_rating")
    positive = _value(subject, "positive_pct")
    if rating is None and positive is None:
        return "warn"  # unknown is never "good"
    buckets = []
    if rating is not None:
        buckets.append("bad" if rating < _HEALTH_BAD_RATING
                       else "warn" if rating < _HEALTH_WARN_RATING else "good")
    if positive is not None:
        buckets.append("bad" if positive < _HEALTH_BAD_POSITIVE
                       else "warn" if positive < _HEALTH_WARN_POSITIVE else "good")
    order = {"bad": 0, "warn": 1, "good": 2}
    return min(buckets, key=lambda b: order[b])
```

- [ ] **Step 4: Run again — expect 6 passed**
- [ ] **Step 5: Commit** the two files: `Add benchmark distribution and north-star summary helpers`

- [ ] **Step 6: Append `distribution()` and `north_star()` to `summary.py`**

```python
def distribution(subjects: list[dict[str, Any]]) -> dict[str, Any]:
    """Best/median/worst/gap per headline metric across available subjects.

    Unavailable subjects and null metric values are excluded — a subject that
    has not been scraped yet must not drag the median down. ``gap`` is
    best − worst (0 when a single subject carries the metric).
    """
    out: dict[str, Any] = {}
    for metric in METRIC_SPECS:
        values: list[tuple[float, str]] = []
        for subject in subjects:
            if not subject.get("available"):
                continue
            value = _value(subject, metric)
            if value is None:
                continue
            values.append((value, subject.get("name") or subject.get("key") or ""))
        if not values:
            continue
        best_value, best_name = max(values, key=lambda pair: pair[0])
        worst_value, worst_name = min(values, key=lambda pair: pair[0])
        out[metric] = {
            "best": {"name": best_name, "value": best_value},
            "median": round(median([v for v, _ in values]), 2),
            "worst": {"name": worst_name, "value": worst_value},
            "gap": round(best_value - worst_value, 2),
            "values": sorted({v for v, _ in values}),
            "max_scale": METRIC_SPECS[metric]["max"],
        }
    return out


def north_star(
    subjects: list[dict[str, Any]], own_keys: list[str]
) -> dict[str, Any] | None:
    """Rank the tenant's own location(s) against the saved bench.

    Ranking metric is ``avg_rating`` (Google's ordering users actually see);
    gaps are leader − best own value per metric. Returns ``None`` when the
    comparison has no own subject so the card renders nothing instead of a
    meaningless rank.
    """
    available = [s for s in subjects if s.get("available")]
    own = [s for s in available if s.get("key") in set(own_keys)]
    if not own:
        return None

    def _sort_key(subject: dict[str, Any]) -> tuple[float, float]:
        rating = _value(subject, "avg_rating")
        velocity = _value(subject, "reviews_per_month") or 0.0
        # Unrated subjects sort last rather than crashing the comparison.
        return (rating if rating is not None else -1.0, velocity)

    ranked = sorted(available, key=_sort_key, reverse=True)
    leader = ranked[0]
    best_own = max(own, key=_sort_key)
    rank = ranked.index(best_own) + 1

    gaps: dict[str, float | None] = {}
    for metric in METRIC_SPECS:
        leader_value = _value(leader, metric)
        own_value = _value(best_own, metric)
        if leader_value is None or own_value is None:
            gaps[metric] = None
        else:
            gaps[metric] = round(leader_value - own_value, 2)

    return {
        "rank": rank,
        "of": len(ranked),
        "own": {"key": best_own.get("key"), "name": best_own.get("name")},
        "leader": {"key": leader.get("key"), "name": leader.get("name")},
        "gaps": gaps,
        "health": health_of(best_own),
    }
```

- [ ] **Step 7: Run** `python -m pytest tests/test_benchmark_summary.py -q -n 0` — expect 6 passed

### Task 2: Wire `summary` + `distribution` into `/compare`

**Files:**
- Modify: `services/api/app/modules/benchmark/router.py` (`compare_places`, payload block ~lines 147–158)

- [ ] **Step 1: Attach to the payload before caching** (so a cache hit serves the same shape)

```python
    from .summary import distribution as metric_distribution, north_star

    subject_records = await compare.compare_subjects(
        db, tenant_id, subjects, days=compare.RANGES[period]
    )
    payload = {
        "range": period,
        "days": compare.RANGES[period],
        "subjects": subject_records,
        "distribution": metric_distribution(subject_records),
        "summary": north_star(
            subject_records, [s for s in subjects if s.startswith("own:")]
        ),
    }
```

- [ ] **Step 2: Run** `python -m pytest tests/test_benchmark_summary.py tests/test_benchmark_compare.py -q -n 0` (existing compare tests must stay green) — expect PASS
- [ ] **Step 3: Commit** — `Expose benchmark summary and distribution on /compare`

### Task 3: Frontend types + TrendChart component

**Files:**
- Modify: `apps/web/lib/api-benchmark.ts` (after `fetchComparison`, ~line 171)
- Create: `apps/web/components/benchmark/TrendChart.tsx`

- [ ] **Step 1: Add response types** — extend `fetchComparison`'s return type and add:

```ts
/* ── North-star summary + distribution (computed server-side) ────────── */

export type Health = "good" | "warn" | "bad";

export interface CompareSummary {
  rank: number;
  of: number;
  own: { key: string; name: string | null };
  leader: { key: string; name: string | null };
  gaps: Partial<Record<"avg_rating" | "reviews_per_month" | "total_reviews" | "positive_pct", number | null>>;
  health: Health;
}

export interface DistributionRow {
  best: { name: string; value: number };
  median: number;
  worst: { name: string; value: number };
  gap: number;
  values: number[];
  max_scale: number | null;
}

export type CompareDistribution = Record<string, DistributionRow>;
```

and update `fetchComparison`'s return type to
`Promise<{ range: CompareRange; days: number | null; subjects: ComparisonSubject[]; summary: CompareSummary | null; distribution: CompareDistribution }>`.

- [ ] **Step 2: Create `TrendChart.tsx`**

```tsx
"use client";

/**
 * Inline-SVG trend lines from /benchmark/history — one line per subject.
 * No chart library: two polylines-worth of math, question-as-title, and no
 * animation so prefers-reduced-motion needs no special case.
 */
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { HistoryPoint, SubjectHistory } from "@/lib/api-benchmark";

const COLORS = ["#3D1D6E", "#B0338A", "#FF4F6E", "#6B3FB5", "#D8459F", "#FF6E85"];
const W = 320, H = 96, PAD = 8;

function perMonth(points: HistoryPoint[]): { x: number; y: number }[] {
  const dated = points
    .filter((p) => p.at && p.reviews != null)
    .map((p) => ({ t: new Date(p.at as string).getTime(), reviews: p.reviews as number }))
    .sort((a, b) => a.t - b.t);
  const out: { x: number; y: number }[] = [];
  for (let i = 1; i < dated.length; i++) {
    const days = (dated[i].t - dated[i - 1].t) / 86_400_000;
    if (days <= 0) continue;
    out.push({ x: dated[i].t, y: ((dated[i].reviews - dated[i - 1].reviews) / days) * 30 });
  }
  return out;
}

function ratingPoints(points: HistoryPoint[]): { x: number; y: number }[] {
  return points
    .filter((p) => p.at && p.rating != null)
    .map((p) => ({ x: new Date(p.at as string).getTime(), y: p.rating as number }))
    .sort((a, b) => a.x - b.x);
}

function scale(series: { x: number; y: number }[], yMin: number, yMax: number): string {
  if (series.length === 0) return "";
  const xs = series.map((p) => p.x);
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || 1;
  const span = Math.max(yMax - yMin, 0.0001);
  return series
    .map((p) => {
      const px = PAD + ((p.x - x0) / (x1 - x0)) * (W - 2 * PAD);
      const py = H - PAD - ((p.y - yMin) / span) * (H - 2 * PAD);
      return `${px.toFixed(1)},${py.toFixed(1)}`;
    })
    .join(" ");
}

export default function TrendChart({ history, title }: { history: SubjectHistory[]; title: string }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const live = history.filter((s) => s.points.length >= 2);
  if (live.length === 0) return null;
  return (
    <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{title}</h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        {([
          { key: "rating", label: b.trendRatingLabel, series: live.map((s) => ratingPoints(s.points)), yMin: 1, yMax: 5 },
          { key: "velocity", label: b.trendVelocityLabel, series: live.map((s) => perMonth(s.points)), yMin: 0, yMax: Math.max(1, ...live.flatMap((s) => perMonth(s.points).map((p) => p.y))) },
        ] as const).map((chart) => (
          <figure key={chart.key} className="m-0">
            <svg viewBox={`0 0 ${W} ${H}`} className="h-24 w-full" role="img" aria-label={`${chart.label}: ${title}`}>
              <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--ui-line)" strokeWidth="1" />
              {chart.series.map((series, i) => (
                <polyline
                  key={i}
                  points={scale(series, chart.yMin, chart.yMax)}
                  fill="none"
                  stroke={COLORS[i % COLORS.length]}
                  strokeWidth="2"
                  strokeLinejoin="round"
                />
              ))}
            </svg>
            <figcaption className="mt-1 text-[11px] text-[#3B2D5E]">{chart.label}</figcaption>
          </figure>
        ))}
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-[#3B2D5E]">
        {live.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-2 w-4 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
            {s.name ?? s.key}
          </li>
        ))}
      </ul>
    </section>
  );
}
```

- [ ] **Step 3: `cd apps/web; npx tsc --noEmit` — expect clean** (i18n keys `trendRatingLabel`/`trendVelocityLabel` are added in Task 6; add them together if tsc complains)

### Task 4: NorthStarCard + DistributionStrip components

**Files:**
- Create: `apps/web/components/benchmark/NorthStarCard.tsx`
- Create: `apps/web/components/benchmark/DistributionStrip.tsx`

- [ ] **Step 1: Create `NorthStarCard.tsx`**

```tsx
"use client";

import Link from "next/link";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { CompareSummary } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";
const PILL: Record<CompareSummary["health"], string> = {
  good: "bg-[#E7F6EC] text-[#116631]",
  warn: "bg-[#FFF3D6] text-[#8A6100]",
  bad: "bg-[#FDE8EC] text-[#B3123A]",
};

/** Rank "X of Y", gap-to-leader per metric, health pill, fix-first CTA. */
export default function NorthStarCard({
  summary,
  problemTopic,
}: {
  summary: CompareSummary;
  problemTopic: string | null;
}) {
  const { t } = useI18n();
  const b = t.benchmark;
  const gapLabels: Array<[keyof CompareSummary["gaps"], string]> = [
    ["avg_rating", b.metricRating],
    ["reviews_per_month", b.metricVelocity],
    ["total_reviews", b.metricTotalReviews],
    ["positive_pct", b.metricSentiment],
  ];
  const worst = gapLabels
    .map(([key, label]) => ({ key, label, gap: summary.gaps[key] }))
    .filter((g): g is { key: string; label: string; gap: number } => typeof g.gap === "number" && g.gap > 0)
    .sort((a, c) => c.gap - a.gap)[0];
  return (
    <section className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <div className="flex items-center gap-3">
        <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold uppercase ${PILL[summary.health]}`}>
          {b[`health_${summary.health}` as const]}
        </span>
        <p className="text-[14px] font-bold text-[#14101F]">
          {b.rankLine
            .replace("{rank}", String(summary.rank))
            .replace("{of}", String(summary.of))}
        </p>
        {summary.leader?.name ? (
          <p className="text-[12px] text-[#3B2D5E]">{b.leaderLine.replace("{leader}", summary.leader.name)}</p>
        ) : null}
      </div>
      {worst ? (
        <Link
          href="/dashboard/reviews"
          className={`rounded-[24px] bg-[#3D1D6E] px-4 py-2 text-[12px] font-bold text-white ${FOCUS}`}
        >
          {b.fixFirst.replace("{metric}", worst.label)}
        </Link>
      ) : null}
    </section>
  );
}
```

- [ ] **Step 2: Create `DistributionStrip.tsx`**

```tsx
"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { CompareDistribution } from "@/lib/api-benchmark";

/** Best / Median / Worst / Gap bars for the four headline metrics. */
export default function DistributionStrip({ distribution }: { distribution: CompareDistribution }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const rows: Array<[keyof CompareDistribution, string]> = [
    ["avg_rating", b.metricRating],
    ["reviews_per_month", b.metricVelocity],
    ["total_reviews", b.metricTotalReviews],
    ["positive_pct", b.metricSentiment],
  ];
  const visible = rows.filter(([key]) => distribution[key]);
  if (visible.length === 0) return null;
  const fmt = (key: string, v: number) =>
    key === "avg_rating" ? v.toFixed(1) : key === "positive_pct" ? `${v.toFixed(0)}%` : String(Math.round(v));
  return (
    <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.distributionTitle}</h2>
      <div className="mt-3 space-y-3">
        {visible.map(([key, label]) => {
          const row = distribution[key];
          const scale = row.max_scale ?? row.best.value || 1;
          return (
            <div key={key}>
              <div className="flex items-center justify-between text-[11px] text-[#3B2D5E]">
                <span className="font-bold text-[#14101F]">{label}</span>
                <span>{b.gapLine.replace("{gap}", fmt(key, row.gap))}</span>
              </div>
              {([
                [b.distBest, row.best, "#116631"],
                [b.distMedian, { name: "", value: row.median }, "#8A6100"],
                [b.distWorst, row.worst, "#B3123A"],
              ] as const).map(([tag, cell, color]) => (
                <div key={tag} className="mt-1 flex items-center gap-2">
                  <span className="w-12 shrink-0 text-[10px] font-bold uppercase text-[#3B2D5E]">{tag}</span>
                  <div className="h-3 flex-1 overflow-hidden rounded-full bg-[#F1F2F5]">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${Math.max(2, Math.min(100, (cell.value / scale) * 100))}%`, background: color }}
                    />
                  </div>
                  <span className="w-28 shrink-0 truncate text-[11px] text-[#3B2D5E]">
                    {cell.name ? `${cell.name} · ` : ""}{fmt(key, cell.value)}
                  </span>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 3: `npx tsc --noEmit` — expect clean**

### Task 6: Render on the compare page + i18n

**Files:**
- Modify: `apps/web/app/dashboard/benchmark/compare/page.tsx`
- Modify: `apps/web/lib/i18n/en.ts`, `apps/web/lib/i18n/ar.ts` (inside the existing `benchmark:` block)

- [ ] **Step 1: Add i18n keys**

`en.ts` (inside `benchmark: {`):

```ts
      metricRating: "Rating",
      metricVelocity: "Reviews / month",
      metricVelocityShort: "Reviews/mo",
      metricTotalReviews: "Total reviews",
      metricSentiment: "Positive share",
      metricFiveStar: "5★ share",
      health_good: "Healthy",
      health_warn: "Watch",
      health_bad: "At risk",
      rankLine: "You rank #{rank} of {of}",
      leaderLine: "{leader} leads this set",
      fixFirst: "Fix {metric} first",
      distributionTitle: "Where you stand",
      distBest: "Best",
      distMedian: "Median",
      distWorst: "Worst",
      gapLine: "Gap {gap}",
      trendTitle: "Where is it heading?",
      trendRatingLabel: "Average rating over time",
      trendVelocityLabel: "New reviews per month",
      ownScorecardsTitle: "Your branches",
      varianceFlag: "{pct}% off your median",
      topProblemLine: "Top problem: {problem}",
```

`ar.ts` (same keys):

```ts
      metricRating: "التقييم",
      metricVelocity: "المراجعات / شهر",
      metricVelocityShort: "مراجعة/شهر",
      metricTotalReviews: "إجمالي المراجعات",
      metricSentiment: "نسبة الإيجابية",
      metricFiveStar: "نسبة 5★",
      health_good: "بخير",
      health_warn: "للمتابعة",
      health_bad: "معرض للخطر",
      rankLine: "ترتيبك #{rank} من {of}",
      leaderLine: "{leader} يتصدّر هذه المجموعة",
      fixFirst: "ابدأ بإصلاح {metric}",
      distributionTitle: "أين تقف الآن",
      distBest: "الأفضل",
      distMedian: "الوسيط",
      distWorst: "الأدنى",
      gapLine: "الفارق {gap}",
      trendTitle: "إلى أين يتجه الأداء؟",
      trendRatingLabel: "متوسط التقييم عبر الزمن",
      trendVelocityLabel: "مراجعات جديدة شهريًا",
      ownScorecardsTitle: "فروعك",
      varianceFlag: "أقل بمقدار {pct}% من وسيطك",
      topProblemLine: "أهم مشكلة: {problem}",
```

- [ ] **Step 2: Render on the compare page** — inside `ComparePage`'s return, directly above the existing `<MatrixTable>`-rendering section (after the range selector `<section>`), insert:

```tsx
      {compareQuery.data?.summary ? (
        <NorthStarCard
          summary={compareQuery.data.summary}
          problemTopic={null}
        />
      ) : null}
      {compareQuery.data?.distribution ? (
        <DistributionStrip distribution={compareQuery.data.distribution} />
      ) : null}
      <TrendChart history={historyQuery.data?.subjects ?? []} title={b.trendTitle} />
      <OwnScorecards subjects={compareQuery.data?.subjects ?? []} />
```

with imports at the top of the file:

```tsx
import TrendChart from "@/components/benchmark/TrendChart";
import NorthStarCard from "@/components/benchmark/NorthStarCard";
import DistributionStrip from "@/components/benchmark/DistributionStrip";
import OwnScorecards from "@/components/benchmark/OwnScorecards";
```

(If the page defines a local `b` alias already, reuse it; otherwise add `const b = t.benchmark;`.)

- [ ] **Step 3: `npx tsc --noEmit` clean, then `npm run build` passes**
- [ ] **Step 4: Commit** — `Add benchmark north-star, distribution, trend and scorecards to compare page`

### Task 7: Verification + docs

- [ ] `cd services/api; python -m pytest tests/test_benchmark_summary.py -q -n 0` — 6 passed; run the existing benchmark compare tests file(s) found via `ls tests/test_benchmark*` — all pass
- [ ] `cd apps/web; npx tsc --noEmit` clean; `npm run build` passes
- [ ] Update `readiness-report.html`: the four "Now" rows → `<span class="chip ok">Done</span>` with a one-line note ("server-computed summary/distribution + inline-SVG trend/scorecards, no new deps")
- [ ] Commit docs — `Mark benchmark Now-tier items done in readiness report`
- [ ] **Do not push** — the user pushes when ready

### Task 5: OwnScorecards component

**Files:**
- Create: `apps/web/components/benchmark/OwnScorecards.tsx`
- Create: `apps/web/lib/benchmark-stats.ts`

**Scope note:** the readiness row also lists "response rate" per branch, but `ComparisonSubject.metrics` has no reply-rate field yet (neither side of the comparison computes one). The card ships with rating / velocity / five-star share / top problem / variance flag; response rate joins when the backend exposes it (P1 plan, not this one).

- [ ] **Step 1: Create the component** — per own branch: rating, reviews/month velocity, five-star share, top problem, and a variance flag when the branch's rating deviates more than 35% from the own-set median:

```tsx
"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import { median } from "@/lib/benchmark-stats";
import type { ComparisonSubject } from "@/lib/api-benchmark";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

/** One scorecard per own branch + a variance flag (>35% off the own median). */
export default function OwnScorecards({ subjects }: { subjects: ComparisonSubject[] }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const own = subjects.filter((s) => s.kind === "own" && s.available);
  if (own.length === 0) return null;
  const ratings = own.map((s) => s.metrics.avg_rating).filter((v): v is number => v != null);
  const ownMedian = median(ratings);
  return (
    <section className="mt-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.ownScorecardsTitle}</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {own.map((s) => {
          const rating = s.metrics.avg_rating;
          const velocity = s.metrics.reviews_last_month ?? (s.metrics.reviews_last_year != null ? Math.round(s.metrics.reviews_last_year / 12) : null);
          const fiveShare = s.metrics.total_ratings ? Math.round(((s.metrics.five_star ?? 0) / s.metrics.total_ratings) * 100) : null;
          const variance = rating != null && ownMedian != null && ownMedian > 0
            ? Math.abs(rating - ownMedian) / ownMedian : null;
          const flagged = variance != null && variance > 0.35;
          return (
            <article key={s.key} className={`rounded-[8px] border bg-white p-3 ${flagged ? "border-[#B3123A]" : "border-[var(--ui-line)]"}`}>
              <header className="flex items-center justify-between">
                <h3 className="text-[13px] font-bold text-[#14101F]">{s.name}</h3>
                {flagged ? (
                  <span className={`rounded-full bg-[#FDE8EC] px-2 py-0.5 text-[10px] font-bold text-[#B3123A] ${FOCUS}`}>
                    {b.varianceFlag.replace("{pct}", String(Math.round((variance ?? 0) * 100)))}
                  </span>
                ) : null}
              </header>
              <dl className="mt-2 grid grid-cols-3 gap-2 text-center">
                <div><dt className="text-[10px] uppercase text-[#3B2D5E]">{b.metricRating}</dt><dd className="text-[15px] font-bold text-[#14101F]">{rating?.toFixed(1) ?? "—"}</dd></div>
                <div><dt className="text-[10px] uppercase text-[#3B2D5E]">{b.metricVelocityShort}</dt><dd className="text-[15px] font-bold text-[#14101F]">{velocity ?? "—"}</dd></div>
                <div><dt className="text-[10px] uppercase text-[#3B2D5E]">{b.metricFiveStar}</dt><dd className="text-[15px] font-bold text-[#14101F]">{fiveShare != null ? `${fiveShare}%` : "—"}</dd></div>
              </dl>
              {s.facts.top_problems.length > 0 ? (
                <p className="mt-2 text-[11px] text-[#3B2D5E]">{b.topProblemLine.replace("{problem}", s.facts.top_problems[0])}</p>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Create `apps/web/lib/benchmark-stats.ts`** — the one shared math helper both this component and tests use:

```ts
/** Median of a non-empty number list; null for empty input. */
export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
```

- [ ] **Step 3: `npx tsc --noEmit` — expect clean**

---
