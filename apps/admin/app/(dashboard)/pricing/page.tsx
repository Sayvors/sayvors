"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchPricing,
  savePricing,
  type PricingKind,
  type PricingRateRow,
} from "@/lib/pricing-api";

const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";
const INPUT =
  "w-full rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] tabular-nums text-ink outline-none transition focus:border-deep-violet";

const KIND_ORDER: PricingKind[] = ["llm_input", "llm_output", "asr_minute", "tts_kchar"];
const KIND_HELP: Record<PricingKind, string> = {
  llm_input: "What the tenant pays for prompt tokens. Defaults are provider pass-through.",
  llm_output: "What the tenant pays for completion tokens.",
  asr_minute: "Charged per started minute of audio. 0 = voice transcription is free.",
  tts_kchar: "Charged per 1,000 characters spoken. 0 = voice replies are free.",
};

const usd = (cents: number) => `$${(cents / 100).toFixed(cents < 100 ? 4 : 2)}`;

/** Human translation of a rate: dollars per 1M tokens, tokens per dollar. */
function explain(kind: PricingKind, cents: number): string {
  if (cents <= 0) return "free — no wallet debit";
  if (kind === "llm_input" || kind === "llm_output") {
    const tokensPerDollar = (1_000_000 * 100) / cents;
    const perMillion = `$${(cents / 100).toFixed(cents % 1 === 0 ? 2 : 4)} per 1M`;
    return `${perMillion} · ≈ ${tokensPerDollar >= 1_000_000
      ? `${(tokensPerDollar / 1_000_000).toFixed(2)}M`
      : `${Math.round(tokensPerDollar / 1000)}k`} tokens per $1`;
  }
  if (kind === "asr_minute") return `$${(cents / 100).toFixed(2)} per minute · ${usd(cents * 60)} per audio hour`;
  return `${usd(cents)} per 1k chars · ${usd(cents * 1000)} per 1M chars`;
}

export default function AdminPricingPage() {
  const [rows, setRows] = useState<PricingRateRow[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchPricing()
      .then((data) => {
        setRows(data);
        setDraft(
          Object.fromEntries(
            data.map((r) => [`${r.kind}:${r.key}`, String(r.unit_price_cents)]),
          ),
        );
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load rates."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const grouped = useMemo(
    () =>
      KIND_ORDER.map((kind) => ({
        kind,
        label: rows.find((r) => r.kind === kind)?.label ?? kind,
        rows: rows.filter((r) => r.kind === kind),
      })),
    [rows],
  );

  const save = useCallback(async (row: PricingRateRow) => {
    const raw = draft[`${row.kind}:${row.key}`];
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) {
      setError("Enter a rate of 0 or more (cents per unit).");
      return;
    }
    setBusy(`${row.kind}:${row.key}`);
    setError(null);
    setNotice(null);
    try {
      await savePricing(row.kind, row.key, value);
      setNotice(`${row.label} · ${row.key} set to ${value} cents. Applies to the next call.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  }, [draft, load]);

  return (
    <div className="space-y-4">
      <div className="admin-rise flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-ink/40">Sayvors · Admin</p>
          <h1 className="mt-1 text-[22px] font-bold tracking-tight text-ink">Pricing</h1>
          <p className="mt-1.5 max-w-[760px] text-[14px] font-medium leading-relaxed text-ink sm:text-[15px]">
            The billable rate card. Every LLM call and every billed voice minute is priced from
            here — the wallet is debited in <b className="font-bold text-deep-violet">US cents</b>.
            Change a number, save, and the next call uses it; no deploy or restart.
          </p>
        </div>
        <button
          onClick={load}
          className={`shrink-0 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet ${FOCUS_RING}`}
        >
          Refresh
        </button>
      </div>

      <div className="rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3.5 py-3 text-[12px] leading-relaxed text-ink/70">
        <b className="font-bold text-ink">How the math works:</b> a call costs
        <code className="mx-1 rounded bg-ink/[0.05] px-1">prompt_tokens / 1M × input rate</code>
        +
        <code className="mx-1 rounded bg-ink/[0.05] px-1">completion_tokens / 1M × output rate</code>,
        rounded up to the next cent. Voice is post-paid: minutes × the ASR rate, charged after the
        note is transcribed. A rate of <b className="font-bold">0</b> means that meter is off.
        <span className="mt-1 block text-ink/45">
          100 ¢ = $1.00. So 100 ¢/1M tokens = $1 per 1M tokens; the groq default of 15 ¢/1M =
          $0.15 per 1M, i.e. about 6.7M tokens per $1.
        </span>
      </div>

      {error ? (
        <div role="alert" className="rounded-[2px] border border-red-200 bg-red-50 px-3 py-2.5 text-[12px] text-red-700">{error}</div>
      ) : null}
      {notice ? (
        <div className="rounded-[2px] border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-[12px] text-emerald-800">{notice}</div>
      ) : null}

      {loading ? (
        <div className="grid gap-3" aria-hidden aria-label="Loading rates">
          {[1, 2, 3].map((i) => <div key={i} className="h-40 animate-pulse rounded-[2px] bg-ink/[0.04]" />)}
        </div>
      ) : (
        <div className="grid gap-3">
          {grouped.map((group) => (
            <section key={group.kind} className="panel p-4 sm:p-5" aria-labelledby={`kind-${group.kind}`}>
              <h2 id={`kind-${group.kind}`} className="text-[13px] font-bold text-ink">{group.label}</h2>
              <p className="mt-1 text-[11px] leading-relaxed text-ink/50">{KIND_HELP[group.kind]}</p>
              <div className="mt-3 overflow-hidden rounded-[2px] border border-[var(--ui-line)]">
                <div className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1.4fr)_auto] gap-3 border-b border-[var(--ui-line)] bg-ink/[0.02] px-3 py-2 text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 sm:grid">
                  <span>Key</span>
                  <span>Rate ({group.kind === "asr_minute" ? "US ¢/min" : group.kind === "tts_kchar" ? "US ¢/1k chars" : "US ¢/1M tokens"})</span>
                  <span>Means</span>
                  <span className="sr-only">Save</span>
                </div>
                {group.rows.map((row) => {
                  const id = `${row.kind}:${row.key}`;
                  const value = Number(draft[id] ?? row.unit_price_cents);
                  return (
                    <div
                      key={id}
                      className="grid gap-2 border-b border-[var(--ui-line)] px-3 py-2.5 last:border-b-0 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1.4fr)_auto] sm:items-center sm:gap-3"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-[12px] font-bold text-ink">{row.key}</p>
                        <p className="text-[10px] text-ink/35">
                          default {row.default_cents}¢{row.overridden ? " · overridden" : ""}
                        </p>
                      </div>
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={draft[id] ?? String(row.unit_price_cents)}
                        onChange={(e) => setDraft((prev) => ({ ...prev, [id]: e.target.value }))}
                        className={`${INPUT} ${FOCUS_RING}`}
                        aria-label={`${row.label} ${row.key} rate in cents`}
                      />
                      <p className="text-[11px] text-ink/45">{explain(row.kind, Number.isFinite(value) ? value : 0)}</p>
                      <button
                        onClick={() => save(row)}
                        disabled={busy === id}
                        className={`rounded-[2px] bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50 ${FOCUS_RING}`}
                      >
                        {busy === id ? "Saving…" : "Save"}
                      </button>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}

      <p className="pb-2 text-center text-[11px] text-ink/25">
        Rates are what the tenant is charged, not what the provider charges you. Use the margin you
        want; the defaults are pass-through.
      </p>
    </div>
  );
}
