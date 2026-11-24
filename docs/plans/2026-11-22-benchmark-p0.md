# Benchmark P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the benchmark page feel like a product: a named, persisted benchmark set (max 5 competitors) that drives the compare page by default, gap-vs-you chips in the existing matrix, sentiment/volume bars, and no more all-tied noise rows in the distribution strip.

**Architecture:** One backend flag (`BenchmarkPlace.in_bench_set`, mirroring the existing `in_heatmap` pattern) with a server-enforced 5-set cap; the compare page auto-defaults its URL selection to own-location + bench set when the URL is bare. The existing `MatrixTable` gains generic gap-vs-main chips (no second matrix — the review confirmed one already exists). One new presentational component (sentiment/volume bars) fed entirely by the existing compare payload.

**Tech Stack:** FastAPI + SQLAlchemy + Alembic (one migration, single head `20261122101000`), Next.js/React + TanStack Query, pytest, no new deps.

**Scope note:** P1 (action-rate KPI, completeness checklist, fix-first tickets, AI summary, sparklines) and P2 stay out. The readiness "quick fix" (tied-metric collapse in DistributionStrip) is Task 6 here.

---

## File Structure

| File | Responsibility |
| --- | --- |
| Modify `services/api/app/modules/benchmark/models.py` | `in_bench_set` column on `BenchmarkPlace`. |
| Create `services/api/alembic/versions/20261122110000_bench_set_flag.py` | Idempotent `ADD COLUMN IF NOT EXISTS` + partial index; `down_revision = "20261122101000"`. |
| Modify `services/api/app/modules/benchmark/service.py` | `set_bench_set()` (cap 5, `with_for_update()`), `serialize()` field. |
| Modify `services/api/app/modules/benchmark/router.py` | `POST /places/{place_id}/bench-set`. |
| Create `services/api/tests/test_benchmark_bench_set.py` | Toggle/cap/404/serialize tests. |
| Modify `apps/web/lib/api-benchmark.ts` | `in_bench_set` on `SavedPlace`, `setBenchmarkSet()`. |
| Modify `apps/web/app/dashboard/benchmark/page.tsx` | Set toggle + n/5 counter on saved cards. |
| Modify `apps/web/app/dashboard/benchmark/compare/page.tsx` | Bare-URL default selection (own + bench set); gap chips in `MatrixTable`; mount `SentimentVelocityBars`. |
| Create `apps/web/components/benchmark/SentimentVelocityBars.tsx` | Stacked sentiment bar + reviews/month per subject. |
| Modify `apps/web/components/benchmark/DistributionStrip.tsx` | Tied-metric collapse. |
| Modify `apps/web/lib/i18n/en.ts`, `ar.ts` | New copy. |

---

### Task 1: Backend bench-set flag (TDD)

**Files:**
- Modify: `services/api/app/modules/benchmark/models.py` (after `in_heatmap`, ~line 49)
- Create: `services/api/alembic/versions/20261122110000_bench_set_flag.py`
- Modify: `services/api/app/modules/benchmark/service.py` (`serialize` ~line 40, new `set_bench_set` near `toggle_heatmap` ~line 242)
- Modify: `services/api/app/modules/benchmark/router.py` (near `set_heatmap` ~line 233)
- Test: `services/api/tests/test_benchmark_bench_set.py` (model it on the bench fixtures in `tests/test_benchmark_bench.py`)

- [ ] **Step 1: Write the failing tests** — cover: default flag False on save; toggle on → True in `serialize`; toggle off; unknown place → 404; adding a 6th member → HTTP 422 with a "benchmark set is full" detail; flag survives `list_saved`.

```python
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
```

- [ ] **Step 2: Run** `cd services/api; python -m pytest tests/test_benchmark_bench_set.py -q -n 0` — expect FAIL (`set_bench_set` missing / column missing). If the `db`/`user_id` fixtures differ in name in `tests/test_benchmark_bench.py`, match that file's fixture usage exactly.
- [ ] **Step 3: Model + migration**

`models.py` after `in_heatmap`:

```python
    # Membership in the tenant's named benchmark set (max 5, enforced in
    # service.set_bench_set). Drives the compare page's default selection;
    # in_heatmap stays independent (heatmap ≠ benchmark set).
    in_bench_set: Mapped[bool] = mapped_column(default=False)
```

`20261122110000_bench_set_flag.py`:

```python
"""benchmark set membership flag on saved places

Revision ID: 20261122110000
Revises: 20261122101000
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122110000"
down_revision = "20261122101000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE benchmark_places "
        "ADD COLUMN IF NOT EXISTS in_bench_set BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_benchmark_places_bench_set "
        "ON benchmark_places (tenant_id) WHERE in_bench_set"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_benchmark_places_bench_set")
    op.execute("ALTER TABLE benchmark_places DROP COLUMN IF EXISTS in_bench_set")
```

- [ ] **Step 4: Service + router**

`service.py` — add to `serialize` (next to `"in_heatmap"`): `"in_bench_set": place.in_bench_set,`. New function near `toggle_heatmap`:

```python
BENCH_SET_MAX = 5


async def set_bench_set(
    db: AsyncSession, tenant_id: str, place_id: str, *, enabled: bool | None = None
) -> BenchmarkPlace:
    """Toggle a saved place's membership in the tenant's benchmark set.

    The cap is enforced under a row lock on the tenant's bench so two
    concurrent toggles cannot both pass the count check (AGENTS.md: real
    concurrency). Enabling an already-enabled member is a no-op that must
    not trip the cap.
    """
    row = await get_saved(db, tenant_id, place_id)
    if row is None:
        raise BenchError("Saved place not found")
    new_value = (not row.in_bench_set) if enabled is None else bool(enabled)
    if new_value is False or row.in_bench_set is True:
        row.in_bench_set = new_value
        await db.commit()
        await db.refresh(row)
        return row
    members = (
        await db.execute(
            select(BenchmarkPlace)
            .where(
                BenchmarkPlace.tenant_id == tenant_id,
                BenchmarkPlace.in_bench_set.is_(True),
            )
            .with_for_update()
        )
    ).scalars().all()
    if len(members) >= BENCH_SET_MAX:
        raise BenchError(
            f"Benchmark set is full ({BENCH_SET_MAX} places). "
            "Remove one before adding another."
        )
    row.in_bench_set = True
    await db.commit()
    await db.refresh(row)
    return row
```

`router.py` after `set_heatmap`:

```python
@router.post("/places/{place_id}/bench-set", response_model=dict)
async def set_bench_set(
    place_id: str,
    enabled: bool | None = Query(default=None),
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await service.set_bench_set(
            db, tenant_id_of(ctx.user), place_id, enabled=enabled
        )
    except service.BenchError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return service.serialize(row)
```

- [ ] **Step 5: Run the scoped tests** — `tests/test_benchmark_bench_set.py` + `tests/test_benchmark_bench.py` green.
- [ ] **Step 6: Commit** — `Add benchmark set membership flag with cap`

### Task 2: Benchmark page — set toggle + counter

**Files:**
- Modify: `apps/web/lib/api-benchmark.ts` (`SavedPlace` interface + new API fn)
- Modify: `apps/web/app/dashboard/benchmark/page.tsx` (saved-card actions, where the heatmap toggle renders)
- Modify: `apps/web/lib/i18n/en.ts`, `ar.ts` (`benchmark:` block)

- [ ] **Step 1: API layer** — add `in_bench_set: boolean;` to `SavedPlace`; add:

```ts
export function setBenchmarkSet(placeId: string, enabled: boolean): Promise<SavedPlace> {
  return apiFetch(`/api/v1/benchmark/places/${encodeURIComponent(placeId)}/bench-set?enabled=${enabled}`, {
    method: "POST",
  });
}
```

- [ ] **Step 2: Page UI** — in the saved-card actions row (next to the heatmap toggle; reuse its `busyId` pattern): a set toggle showing `{b.benchSetIn}`/`{b.benchSetOut}`; disabled when `!place.in_bench_set && benchSetCount >= 5`; header of the saved list gains `{b.benchSetCount.replace("{n}", String(benchSetCount)).replace("{max}", "5")}`. `benchSetCount = saved.filter((p) => p.in_bench_set).length`. On toggle: `await setBenchmarkSet(...)` then invalidate `["benchmark", "saved"]` (same as `toggleHeatmap`).
- [ ] **Step 3: i18n** — `benchSetIn: "In benchmark set"` / ar `"في مجموعة المقارنة"`; `benchSetOut: "Add to benchmark set"` / ar `"أضف إلى مجموعة المقارنة"`; `benchSetCount: "{n} of {max} in your benchmark set"` / ar `"{n} من {max} في مجموعة المقارنة"`; `benchSetFull: "Benchmark set is full (5)"` / ar `"المجموعة ممتلئة (5)"`.
- [ ] **Step 4: `npx tsc --noEmit` clean.**

### Task 3: Compare page defaults from the bench set

**Files:**
- Modify: `apps/web/app/dashboard/benchmark/compare/page.tsx` (selection block ~lines 1086–1097)

- [ ] **Step 1: Bare-URL default** — when the URL has neither `main` nor `vs`, auto-apply once once both queries settle:

```tsx
  const benchSet = useMemo(
    () => saved.filter((p) => p.in_bench_set).slice(0, 5),
    [saved]
  );
  const bareUrl = !params.get("main") && !params.get("vs");
  const defaultsReady = benchSet.length >= 0 && own.length >= 0 && (savedQuery.isSuccess || savedQuery.isError) && (channelsQuery.isSuccess || channelsQuery.isError);
  const appliedDefaults = useRef(false);
  useEffect(() => {
    if (!bareUrl || !defaultsReady || appliedDefaults.current) return;
    appliedDefaults.current = true;
    const main = own[0] ? subjectKey("own", own[0].id) : null;
    const competitors = benchSet
      .map((p) => subjectKey("saved", p.place_id))
      .filter((key) => key !== main)
      .slice(0, 5);
    if (main || competitors.length > 0) {
      update({ main, competitors });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- runs once when data is ready
  }, [bareUrl, defaultsReady]);
```

(`useRef` import: the file already imports React hooks — extend the existing import. `subjectKey` is already exported from `api-benchmark.ts`; import it if missing. `update` is the page's existing selection setter. Once applied, the URL is populated so `bareUrl` flips false — the guard only prevents double-application before the router updates.)

- [ ] **Step 2: `npx tsc --noEmit` clean.**

### Task 4: Gap-vs-main chips in MatrixTable

**Files:**
- Modify: `apps/web/app/dashboard/benchmark/compare/page.tsx` (`Row` type, `getMetricRows`, `MatrixTable` cells)

- [ ] **Step 1: Row contract** — extend `Row<T>` with optional `higherIsBetter?: boolean` and optional numeric accessor already present via `value`. Mark the four headline metric rows in `getMetricRows` (rating, reviews/month, total reviews, positive share) with `higherIsBetter: true`. Do NOT add it to fact/period rows.
- [ ] **Step 2: Chip computation in `MatrixTable`** — for a row with `higherIsBetter` and a main subject available, each non-main cell with numeric values gets a diff chip:

```tsx
// Gap chip: how this business differs from the tenant's own column.
// Signed diff, colored by whether the direction helps (row-defined).
function gapChip(
  value: number | null,
  mainValue: number | null,
  higherIsBetter: boolean | undefined,
  copy: typeof en.benchmark.compare,
): { text: string; className: string } | null {
  if (value == null || mainValue == null || value === mainValue) return null;
  const diff = value - mainValue;
  const helps = higherIsBetter ? diff > 0 : diff < 0;
  const sign = diff > 0 ? "+" : "\u2212";
  return {
    text: `${sign}${Math.abs(Math.round(diff * 10) / 10)}`,
    className: helps
      ? "bg-[#E7F6EC] text-[#116631]"
      : "bg-[#FDE8EC] text-[#B3123A]",
  };
}
```

Render the chip under the cell value (`<span className={mt-1 inline-block rounded-full px-1.5 py-0.5 text-[10px] font-bold ${className}}>{text}</span>`) when non-null; nothing when the subject is the main column. Numeric extraction: reuse each row's `value(subject)`; wrap in `Number.isFinite` checks — if a row's accessor returns a non-number, no chip.
- [ ] **Step 3: `npx tsc --noEmit` clean.**

### Task 5: SentimentVelocityBars component

**Files:**
- Create: `apps/web/components/benchmark/SentimentVelocityBars.tsx`
- Modify: `apps/web/app/dashboard/benchmark/compare/page.tsx` (mount after DistributionStrip, before TrendChart)
- Modify: i18n (en/ar): `sentimentVolumeTitle`, `sentimentPositive`, `sentimentNeutral`, `sentimentNegative`

- [ ] **Step 1: Component** — one row per available subject with sentiment facts: stacked bar (`positive_pct` / neutral / `negative_pct`, neutral = `100 − pos − neg` clamped ≥ 0; skip the subject when both pos and neg are null) + right-aligned velocity (`metrics.reviews_last_month ?? round(reviews_last_year / 12)`; `—` when unknown, per repo rule). Solid segments only: `#116631` / `#D8D8DC` / `#B3123A`. Grid layout mirrors OwnScorecards.

```tsx
"use client";

import { useI18n } from "@/lib/i18n/I18nProvider";
import type { ComparisonSubject } from "@/lib/api-benchmark";

/** Reputation mix (stacked) + review velocity per compared business. */
export default function SentimentVelocityBars({ subjects }: { subjects: ComparisonSubject[] }) {
  const { t } = useI18n();
  const b = t.benchmark;
  const rows = subjects
    .filter((s) => s.available)
    .map((s) => {
      const pos = s.facts.positive_pct;
      const neg = s.facts.negative_pct;
      if (pos == null && neg == null) return null;
      const p = pos ?? 0;
      const n = neg ?? 0;
      const neutral = Math.max(0, 100 - p - n);
      const velocity = s.metrics.reviews_last_month
        ?? (s.metrics.reviews_last_year != null
          ? Math.round(s.metrics.reviews_last_year / 12)
          : null);
      return { subject: s, p, neutral, n, velocity };
    })
    .filter((r): r is NonNullable<typeof r> => r !== null);
  if (rows.length === 0) return null;
  return (
    <section className="mt-4 rounded-[8px] border border-[var(--ui-line)] bg-white p-3 sm:p-4">
      <h2 className="text-[12px] font-bold uppercase tracking-wide text-[#14101F]">{b.sentimentVolumeTitle}</h2>
      <div className="mt-3 space-y-2.5">
        {rows.map(({ subject, p, neutral, n, velocity }) => (
          <div key={subject.key} className="flex items-center gap-3">
            <span className="w-40 min-w-0 shrink-0 truncate text-[12px] font-semibold text-[#14101F]" title={subject.name ?? undefined}>
              {subject.name ?? subject.key}
            </span>
            <div className="flex h-4 flex-1 overflow-hidden rounded-full bg-[#F1F2F5]" role="img"
              aria-label={`${subject.name}: ${Math.round(p)}% ${b.sentimentPositive}, ${Math.round(neutral)}% ${b.sentimentNeutral}, ${Math.round(n)}% ${b.sentimentNegative}`}>
              <div className="h-full" style={{ width: `${p}%`, background: "#116631" }} />
              <div className="h-full" style={{ width: `${neutral}%`, background: "#D8D8DC" }} />
              <div className="h-full" style={{ width: `${n}%`, background: "#B3123A" }} />
            </div>
            <span className="w-24 shrink-0 text-right text-[11px] text-[#3B2D5E]">
              {velocity != null ? `${velocity} ${b.metricVelocityShort}` : "\u2014"}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[10px] text-[#3B2D5E]">
        {[
          { key: "pos", color: "#116631", label: b.sentimentPositive },
          { key: "neu", color: "#D8D8DC", label: b.sentimentNeutral },
          { key: "neg", color: "#B3123A", label: b.sentimentNegative },
        ].map((item) => (
          <span key={item.key} className="mr-3 inline-flex items-center gap-1">
            <span aria-hidden className="inline-block h-2 w-2 rounded-full" style={{ background: item.color }} />
            {item.label}
          </span>
        ))}
      </p>
    </section>
  );
}
```

- [ ] **Step 2: Mount** in `compare/page.tsx` between DistributionStrip and TrendChart: `<SentimentVelocityBars subjects={compareQuery.data?.subjects ?? []} />`. Add i18n keys: `sentimentVolumeTitle: "Sentiment & review volume"` / ar `"الانطباع وحجم المراجعات"`; `sentimentPositive: "Positive"` / ar `"إيجابي"`; `sentimentNeutral: "Neutral"` / ar `"محايد"`; `sentimentNegative: "Negative"` / ar `"سلبي"`.
- [ ] **Step 3: `npx tsc --noEmit` clean.**

### Task 6: DistributionStrip tied-metric collapse

**Files:**
- Modify: `apps/web/components/benchmark/DistributionStrip.tsx`
- Modify: i18n (en/ar): `tiedLine`

- [ ] **Step 1: Collapse** — when `row.gap === 0` (all subjects share one value), render one compact line instead of the three-bar block:

```tsx
{row.gap === 0 ? (
  <div key={key} className="mt-1 flex items-center justify-between text-[11px] text-[#3B2D5E]">
    <span className="font-bold text-[#14101F]">{label}</span>
    <span>{copy.tiedLine.replace("{value}", fmt(key, row.best.value))}</span>
  </div>
) : (
  /* existing best/median/worst block */
)}
```

(`fmt` and `label` come from the existing map body — restructure the existing `visible.map` callback accordingly.) i18n: `tiedLine: "Everyone tied at {value}"` / ar `"الجميع متعادل عند {value}"`.
- [ ] **Step 2: `npx tsc --noEmit` clean.**

### Task 7: Verification + docs

- [ ] `cd services/api; python -m pytest tests/test_benchmark_bench_set.py tests/test_benchmark_bench.py tests/test_benchmark_summary.py tests/test_benchmark_compare.py -q -n 0` — all green
- [ ] `cd apps/web; npx tsc --noEmit` clean; `npm run build` succeeds
- [ ] `readiness-report.html`: flip the three P0 rows (named competitor set, gap matrix, sentiment/velocity bars) to Done with a one-line note; note the tied-collapse under the distribution row.
- [ ] Commits: backend (`Add benchmark set flag and compare defaults` for Tasks 1+3-backend parts split as they land), frontend (`Add benchmark set UI, gap chips and sentiment bars`), docs (`Mark benchmark P0 items done in readiness report`). **Never push.**

---
