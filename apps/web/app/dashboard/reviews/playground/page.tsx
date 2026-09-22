"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  streamReviewReply,
  listEngineLogs,
  type StreamEvent,
  type EngineLog,
} from "@/lib/api-review-engine";
import { apiFetch } from "@/lib/api-rag";
import { listDatabanks } from "@/lib/api-rag";

const CHANNELS = ["google_review", "facebook", "instagram", "tripadvisor", "yelp"];

type ChannelOpt = { id: string; display_name?: string; platform?: string };


const PRESETS = [
  {
    label: "Angry 1★ (service complaint)",
    review_text: "Terrible service! Waited 45 minutes for cold food and the waiter was rude when I complained. Never coming back.",
    rating: 1,
    reviewer_name: "Sarah M.",
  },
  {
    label: "Happy 5★ (product praise)",
    review_text: "Absolutely loved the margherita pizza! Fresh basil, perfect crust, friendly staff. Best Italian place in town!",
    rating: 5,
    reviewer_name: "James K.",
  },
  {
    label: "Mixed 3★ (question)",
    review_text: "Food was decent but do you have gluten-free options? Also what are your weekend hours?",
    rating: 3,
    reviewer_name: "Priya S.",
  },
  {
    label: "Trap 2★ (refund + staff)",
    review_text: "Charged twice for my order and nobody at the counter would help. I want a refund and the manager's name.",
    rating: 2,
    reviewer_name: "Omar D.",
  },
];

function countWords(s: string): number {
  return (s.match(/[A-Za-z0-9']+/g) ?? []).length;
}

function countSentences(s: string): number {
  return s.split(/[.!?…]+/).filter((x) => x.trim()).length;
}

function StepDot({ active, done }: { active: boolean; done: boolean }) {  return (
    <span
      className={[
        "mt-1 h-2.5 w-2.5 shrink-0 rounded-full",
        done ? "bg-emerald-500" : active ? "animate-pulse bg-deep-violet" : "bg-ink/15",
      ].join(" ")}
    />
  );
}

export default function ReviewPlaygroundPage() {
  const [reviewText, setReviewText] = useState(PRESETS[0].review_text);
  const [rating, setRating] = useState(1);
  const [reviewerName, setReviewerName] = useState(PRESETS[0].reviewer_name);
  const [channel, setChannel] = useState("google_review");
  const [channelId, setChannelId] = useState("");
  const [channels, setChannels] = useState<ChannelOpt[]>([]);
  // DB-driven pickers: tenant enabled models + databanks. Empty = location default.
  const [models, setModels] = useState<{ id: string; name: string; provider: string }[]>([]);
  const [modelPick, setModelPick] = useState("");
  const [banks, setBanks] = useState<{ id: string; name: string }[]>([]);
  const [bankPick, setBankPick] = useState("");
  const [linkedModel, setLinkedModel] = useState<string | null>(null);
  const [linkedBank, setLinkedBank] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<EngineLog[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!running) {
      listEngineLogs(5).then((d) => setLogs(d.logs ?? [])).catch(() => {});
    }
  }, [running]);

  useEffect(() => {
    // Channels for the sync picker (load once)
    (async () => {
      try {
        const { getAccessToken } = await import("@/lib/auth-context");
        const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
        const token = getAccessToken();
        const h: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
        const ch = await fetch(`${API}/api/v1/channels/?limit=100`, { headers: h, credentials: "include" }).then((r) => (r.ok ? r.json() : []));
        setChannels(Array.isArray(ch) ? ch : ch?.channels ?? []);
        const list: ChannelOpt[] = Array.isArray(ch) ? ch : ch?.channels ?? [];
        if (list.length > 0) setChannelId((prev) => prev || list[0].id);
      } catch {
        // picker stays empty — manual channel still works
      }
    })();
  }, []);

  useEffect(() => {
    // Tenant enabled AI models (admin-managed) + databanks — nothing hardcoded.
    (async () => {
      try {
        const m = await apiFetch("/api/v1/llm/models").catch(() => null);
        if (m?.models) setModels(m.models);
      } catch {
        /* picker stays empty */
      }
      try {
        const b = await listDatabanks().catch(() => null);
        if (b?.databanks) setBanks(b.databanks);
      } catch {
        /* picker stays empty */
      }
    })();
  }, []);

  useEffect(() => {
    // Location defaults: its configured model + linked databank.
    if (!channelId) {
      setLinkedModel(null);
      setLinkedBank(null);
      return;
    }
    setModelPick("");
    setBankPick("");
    (async () => {
      try {
        const cfg = await apiFetch(`/api/v1/channels/${channelId}/autoreply`).catch(() => null);
        setLinkedModel(cfg?.model ?? null);
        setLinkedBank(cfg?.databank_id ?? null);
      } catch {
        setLinkedModel(null);
        setLinkedBank(null);
      }
    })();
  }, [channelId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [events]);

  async function handleRun() {
    if (!reviewText.trim() || running) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setRunning(true);
    setEvents([]);
    setError(null);
    try {
      for await (const ev of streamReviewReply(
        {
          review_text: reviewText,
          rating,
          reviewer_name: reviewerName || undefined,
          channel,
          channel_id: channelId || undefined,
          // Explicit picks only — empty means location/tenant default chain.
          model: modelPick || undefined,
          databank_id: bankPick || undefined,
        },
        ctrl.signal
      )) {
        setEvents((prev) => [...prev, ev]);
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setError(e instanceof Error ? e.message : "Stream failed");
      }
    } finally {
      setRunning(false);
    }
  }

  const doneEvent = events.find((e) => e.step === "done");
  const errorEvent = events.find((e) => e.step === "error");
  const analysisEvent = events.find((e) => e.step === "analyzed");
  const issuesEvent = events.find((e) => e.step === "issues");
  const relevanceEvent = events.find((e) => e.step === "relevance");
  const strategies = events.filter((e) => e.step === "strategy");
  const suppressedEvents = events.filter((e) => e.step === "strategy_suppressed");
  const deferredEvents = events.filter((e) => e.step === "strategy_deferred");
  const requirementsEvent = events.find((e) => e.step === "requirements");
  const tier = requirementsEvent?.tier;
  const fulfillmentEvents = events.filter((e) => e.step === "fulfillment");
  const toolCalls = events.filter((e) => e.step === "tool_call" || e.step === "evidence");
  const toolResults = events.filter((e) => e.step === "tool_result" || e.step === "evidence_result");
  const analyzingEvent = events.find((e) => e.step === "analyzing");
  const retrievalEvent = events.find((e) => e.step === "retrieval");
  const bankNameOf = (id: string | null | undefined) =>
    banks.find((b) => b.id === id)?.name ?? (id ? `${id.slice(0, 8)}…` : "none linked");
  const progressEvents = events.filter((e) =>
    ["analyzing", "strategies", "tools", "retrieval", "generating", "validating", "done"].includes(e.step)
  );

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="mx-auto max-w-5xl space-y-5 p-4 sm:p-6">
        {/* Header */}
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Link href="/dashboard/reviews" className="text-[12px] font-medium text-ink/40 hover:text-ink/70">
                ← Reviews
              </Link>
            </div>
            <h1 className="mt-1 text-[20px] font-bold text-ink sm:text-[22px]">AI Engine Playground</h1>
            <p className="mt-0.5 text-[12px] text-ink/65">
              Run a test review through the strategy engine and watch every step live.
            </p>
          </div>
          {running && (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="rounded-xl border border-ink/10 bg-white px-4 py-2 text-[12px] font-semibold text-coral"
            >
              Stop
            </button>
          )}
        </div>

        {/* Input card */}
        <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
          <div className="mb-3 flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                disabled={running}
                onClick={() => {
                  setReviewText(p.review_text);
                  setRating(p.rating);
                  setReviewerName(p.reviewer_name);
                }}
                className="rounded-lg bg-deep-violet/10 px-3 py-1.5 text-[11px] font-semibold text-deep-violet transition hover:bg-deep-violet/20 disabled:opacity-40"
              >
                {p.label}
              </button>
            ))}
          </div>

          <label className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">
            Review text
          </label>
          <textarea
            value={reviewText}
            onChange={(e) => setReviewText(e.target.value)}
            rows={3}
            disabled={running}
            className="mt-1.5 w-full rounded-xl border border-ink/10 bg-white px-3 py-2.5 text-[13px] text-ink outline-none transition focus:border-deep-violet/40 disabled:opacity-60"
          />

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">
                Location
              </label>
              <select
                value={channelId}
                onChange={(e) => setChannelId(e.target.value)}
                disabled={running}
                className="mt-1.5 w-full rounded-xl border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/40 disabled:opacity-60"
              >
                <option value="">Select a location…</option>
                {channels.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.display_name || c.id} {c.platform ? `(${c.platform})` : ""}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-ink/40">
                Engine uses this location&apos;s configured AI — nothing else.
              </p>
            </div>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <label className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">
                AI model
              </label>
              <select
                value={modelPick}
                onChange={(e) => setModelPick(e.target.value)}
                disabled={running || models.length === 0}
                className="mt-1.5 w-full rounded-xl border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/40 disabled:opacity-60"
              >
                <option value="">
                  Location default{linkedModel ? ` (${linkedModel})` : " (tenant default)"}
                </option>
                {models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name} ({m.provider})
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-ink/40">
                Only models your admin enabled — never hardcoded.
              </p>
            </div>
            <div>
              <label className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">
                Data bank
              </label>
              <select
                value={bankPick}
                onChange={(e) => setBankPick(e.target.value)}
                disabled={running || banks.length === 0}
                className="mt-1.5 w-full rounded-xl border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/40 disabled:opacity-60"
              >
                <option value="">
                  Location default{linkedBank ? ` (${bankNameOf(linkedBank)})` : ""}
                </option>
                {banks.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-ink/40">
                Evidence is pulled from this bank for the run.
              </p>
            </div>
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <div>
              <label className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">Rating</label>
              <div className="mt-1.5 flex gap-1">
                {[1, 2, 3, 4, 5].map((r) => (
                  <button
                    key={r}
                    type="button"
                    disabled={running}
                    onClick={() => setRating(r)}
                    className={[
                      "h-9 w-9 rounded-lg text-[14px] font-bold transition",
                      rating === r ? "bg-deep-violet text-white" : "bg-ink/[0.04] text-ink/50 hover:bg-ink/[0.08]",
                    ].join(" ")}
                  >
                    {r}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">Reviewer</label>
              <input
                value={reviewerName}
                onChange={(e) => setReviewerName(e.target.value)}
                disabled={running}
                placeholder="Name (optional)"
                className="mt-1.5 w-full rounded-xl border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/40 disabled:opacity-60"
              />
            </div>
            <div>
              <label className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">Channel</label>
              <select
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                disabled={running}
                className="mt-1.5 w-full rounded-xl border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/40 disabled:opacity-60"
              >
                {CHANNELS.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>

          <button
            type="button"
            onClick={() => void handleRun()}
            disabled={running || !reviewText.trim() || !channelId}
            title={!channelId ? "Select a location first" : undefined}
            className="mt-4 w-full rounded-xl bg-deep-violet px-4 py-3 text-[13px] font-bold text-white shadow-md transition hover:bg-deep-violet/90 disabled:opacity-50 sm:w-auto sm:px-8"
          >
            {running ? "Running…" : "▶ Run through engine"}
          </button>
          {error && (
            <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-[12px] font-medium text-red-600">{error}</p>
          )}
          {errorEvent?.message && (
            <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-[12px] font-medium text-red-600">
              Engine error: {errorEvent.message}
            </p>
          )}
        </div>

        {/* Live progress */}
        {events.length > 0 && (
          <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-[14px] font-bold text-ink">Live trace</h2>
            </div>
            {(analyzingEvent?.model || retrievalEvent) && (
              <p className="mt-1 text-[11px] text-ink/45">
                {analyzingEvent?.model && (
                  <span>
                    Model: <span className="font-mono font-semibold text-ink/70">{analyzingEvent.model}</span>
                    {analyzingEvent?.model_source && <span> ({analyzingEvent.model_source})</span>}
                  </span>
                )}
                {analyzingEvent?.model && retrievalEvent && <span> · </span>}
                {retrievalEvent && (
                  <span>
                    Data bank:{" "}
                    <span className="font-mono font-semibold text-ink/70">
                      {bankNameOf(retrievalEvent.bank_id ?? linkedBank)}
                    </span>
                  </span>
                )}
              </p>
            )}
            <div className="mt-3 space-y-2">
              {progressEvents.map((e, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <StepDot active={i === progressEvents.length - 1 && !doneEvent} done={!!doneEvent || i < progressEvents.length - 1} />
                  <div>
                    <span className="text-[12px] font-semibold capitalize text-ink/80">{e.step}</span>
                    {e.message && <span className="ml-2 text-[12px] text-ink/50">{e.message}</span>}
                    {typeof e.progress === "number" && (
                      <span className="ml-2 text-[11px] text-ink/30">{e.progress}%</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <div ref={bottomRef} />

            {/* Analysis */}
            {relevanceEvent?.relevance && relevanceEvent.relevance.verdict !== "uncertain" && (
              <div
                className={[
                  "mt-4 rounded-2xl p-4",
                  relevanceEvent.relevance.verdict === "off_topic"
                    ? "bg-amber-50/70"
                    : "bg-emerald-50/60",
                ].join(" ")}
              >
                <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-ink/45">
                  Business relevance: {relevanceEvent.relevance.verdict === "off_topic" ? "might be irrelevant" : "on topic"}
                </h3>
                <p className="mt-1 text-[12px] text-ink/65">{relevanceEvent.relevance.reason}</p>
                {relevanceEvent.relevance.evidence && (
                  <p className="mt-0.5 font-mono text-[11px] text-ink/40">{relevanceEvent.relevance.evidence}</p>
                )}
              </div>
            )}

            {analysisEvent?.analysis && (
              <div className="mt-4 rounded-2xl bg-ink/[0.02] p-4">
                <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-ink/45">Analysis</h3>
                <div className="mt-2 flex flex-wrap gap-2 text-[12px]">
                  {Object.entries(analysisEvent.analysis).map(([k, v]) => (
                    <span key={k} className="rounded-lg bg-white px-2.5 py-1 shadow-sm">
                      <span className="font-semibold text-ink/50">{k}:</span>{" "}
                      <span className="font-medium text-ink">{Array.isArray(v) ? v.join(", ") : String(v ?? "—")}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Issues extracted */}
            {issuesEvent?.issues && issuesEvent.issues.length > 0 && (
              <div className="mt-4 rounded-2xl bg-ink/[0.02] p-4">
                <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-ink/45">
                  Issue extraction ({issuesEvent.issues.length})
                </h3>
                <div className="mt-2 space-y-1.5">
                  {issuesEvent.issues.map((iss, i) => (
                    <div key={i} className="rounded-xl bg-white px-3 py-2 text-[12px] shadow-sm">
                      <span className="font-bold text-ink">{iss.label}</span>
                      <span className="ml-2 text-ink/60">{iss.detail}</span>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {iss.keywords.slice(0, 6).map((k, ki) => (
                          <span key={`${k}-${ki}`} className="rounded bg-ink/[0.05] px-1.5 py-0.5 font-mono text-[10px] text-ink/50">
                            {k}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Strategies */}
            {strategies.length > 0 && (
              <div className="mt-4 rounded-2xl bg-ink/[0.02] p-4">
                <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-ink/45">
                  Strategies eligible ({strategies.length})
                </h3>
                <div className="mt-2 space-y-1.5">
                  {strategies.map((e, i) => (
                    <div key={i} className="rounded-xl bg-white px-3 py-2 text-[12px] shadow-sm">
                      <span className="font-bold text-deep-violet">{e.strategy?.name}</span>
                      {e.strategy?.conditional && (
                        <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-700">
                          CONDITIONAL
                        </span>
                      )}
                      <span className="ml-2 text-ink/50">{e.strategy?.reason}</span>
                      {e.strategy?.condition_note && (
                        <p className="mt-0.5 text-[11px] italic text-amber-700">{e.strategy.condition_note}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Suppressed */}
            {suppressedEvents.length > 0 && (
              <div className="mt-4 rounded-2xl bg-red-50/60 p-4">
                <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-red-400">
                  Suppressed by conflict rules ({suppressedEvents.length})
                </h3>
                <div className="mt-2 space-y-1.5">
                  {suppressedEvents.map((e, i) => (
                    <div key={i} className="rounded-xl bg-white px-3 py-2 text-[12px] shadow-sm">
                      <span className="font-bold text-ink/40 line-through">{e.strategy?.name}</span>
                      <p className="mt-0.5 text-[11px] text-ink/50">{e.strategy?.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Deferred — eligible but unused */}
            {deferredEvents.length > 0 && (
              <div className="mt-4 rounded-2xl bg-amber-50/60 p-4">
                <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-amber-600">
                  Deferred — eligible, not executed ({deferredEvents.length})
                </h3>
                <div className="mt-2 space-y-1.5">
                  {deferredEvents.map((e, i) => (
                    <div key={i} className="rounded-xl bg-white px-3 py-2 text-[12px] shadow-sm">
                      <span className="font-bold text-ink/60">{e.strategy?.name}</span>
                      <p className="mt-0.5 text-[11px] text-ink/50">{e.strategy?.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Requirements */}
            {requirementsEvent?.requirements && requirementsEvent.requirements.length > 0 && (
              <div className="mt-4 rounded-2xl bg-ink/[0.02] p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-ink/45">
                    Binding generation requirements ({requirementsEvent.requirements.length})
                  </h3>
                  {tier && (
                    <span className="rounded-full bg-deep-violet/10 px-2.5 py-0.5 text-[11px] font-semibold text-deep-violet">
                      Tier: {tier.label} · ≤{tier.max_sentences} sentences · ~{tier.min_words}–{tier.max_words} words
                    </span>
                  )}
                </div>
                <ul className="mt-2 list-disc space-y-1 pl-5 text-[12px] text-ink/70">
                  {requirementsEvent.requirements.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Tool calls */}
            {(toolCalls.length > 0 || toolResults.length > 0) && (
              <div className="mt-4 rounded-2xl bg-ink/[0.02] p-4">
                <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-ink/45">
                  Databank lookups ({toolCalls.length})
                </h3>
                <div className="mt-2 space-y-1.5">
                  {toolCalls.map((e, i) => {
                    let countLabel: string | null = null;
                    const res = toolResults[i]?.result;
                    if (res) {
                      try {
                        const parsed = JSON.parse(res);
                        if (typeof parsed.count === "number") {
                          countLabel = `${parsed.count} fact${parsed.count === 1 ? "" : "s"}`;
                        }
                      } catch {
                        countLabel = null;
                      }
                    }
                    return (
                      <div key={i} className="rounded-xl bg-white px-3 py-2 text-[12px] shadow-sm">
                        <span className="font-mono font-bold text-emerald-700">
                          🔧 {e.tool ?? (e.need ? `evidence:${e.need}` : "evidence")}
                        </span>
                        {e.args && Object.keys(e.args).length > 0 && (
                          <span className="ml-2 font-mono text-[11px] text-ink/45">{JSON.stringify(e.args)}</span>
                        )}
                        {e.query && (
                          <span className="ml-2 font-mono text-[11px] text-ink/45">“{e.query}”</span>
                        )}
                        {(toolResults[i]?.result || countLabel) && (
                          <p className="mt-1 line-clamp-2 text-ink/60">
                            {countLabel ?? toolResults[i].result}
                          </p>
                        )}
                      </div>
                    );
                  })}
                  {toolCalls.length === 0 && (
                    <p className="text-[12px] text-ink/40">No databank lookup needed for this review.</p>
                  )}
                </div>
              </div>
            )}

            {/* Fulfillment attempts */}
            {fulfillmentEvents.length > 0 && (
              <div className="mt-4 rounded-2xl bg-ink/[0.02] p-4">
                <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-ink/45">
                  Strategy fulfillment ({fulfillmentEvents.length} attempt{fulfillmentEvents.length !== 1 ? "s" : ""})
                </h3>
                {fulfillmentEvents.map((e, ai) => (
                  <div key={ai} className="mt-2">
                    <p className="text-[11px] font-semibold text-ink/50">Attempt {ai + 1}</p>
                    <div className="mt-1 space-y-1.5">
                      {(e.fulfillment ?? []).map((f, i) => (
                        <div key={i} className="rounded-xl bg-white px-3 py-2 text-[12px] shadow-sm">
                          <span
                            className={[
                              "mr-2 inline-block rounded px-1.5 py-0.5 text-[10px] font-bold",
                              f.status === "pass" ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-600",
                            ].join(" ")}
                          >
                            {f.status === "pass" ? "PASS" : "FAIL"}
                          </span>
                          <span className="font-semibold text-ink/80">{f.strategy}</span>
                          <p className="mt-0.5 text-ink/60">{f.reason}</p>
                          {f.evidence && (
                            <p className="mt-0.5 font-mono text-[11px] text-ink/40">“{f.evidence}”</p>
                          )}
                        </div>
                      ))}
                      {(e.validation_issues ?? []).length > 0 && (
                        <p className="text-[11px] text-amber-700">
                          → {(e.validation_issues ?? []).join(" · ")}
                        </p>
                      )}
                      {(e.claims ?? []).length > 0 && (
                        <div className="mt-1.5 space-y-1">
                          {(e.claims ?? []).map((c, i) => (
                            <div key={i} className="rounded-lg bg-ink/[0.03] px-2.5 py-1.5 text-[11px]">
                              <span
                                className={[
                                  "mr-1.5 inline-block rounded px-1.5 py-0.5 text-[10px] font-bold",
                                  c.status === "GROUNDED"
                                    ? "bg-emerald-100 text-emerald-700"
                                    : "bg-red-100 text-red-600",
                                ].join(" ")}
                              >
                                {c.status}
                              </span>
                              <span className="text-ink/70">“{c.claim}”</span>
                              <span className="ml-1.5 text-ink/40">[{c.kind}]</span>
                              {c.source !== "NONE" && (
                                <p className="mt-0.5 font-mono text-[10px] text-ink/45">src: {c.source}</p>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Final response */}
            {doneEvent?.response && (
              <div className="mt-4 rounded-2xl border-2 border-deep-violet/20 bg-deep-violet/[0.03] p-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-[12px] font-bold uppercase tracking-[0.1em] text-ink/45">Generated reply</h3>
                  <span
                    className={[
                      "rounded-full px-2 py-0.5 text-[10px] font-bold",
                      doneEvent.response.validation.passed
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-amber-100 text-amber-700",
                    ].join(" ")}
                  >
                    {doneEvent.response.validation.passed ? "✓ Passed validation" : "⚠ Needs review"}
                  </span>
                </div>
                <p className="mt-2 text-[14px] leading-relaxed text-ink">
                  {doneEvent.response.response_text}
                </p>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-ink/45">
                  <span>Latency: <b>{doneEvent.response.latency_ms}ms</b></span>
                  <span>
                    Length: <b>{countWords(doneEvent.response.response_text)} words / {countSentences(doneEvent.response.response_text)} sentences</b>
                    {tier && (
                      <span className="text-ink/35"> (tier ≤{tier.max_words}w / ≤{tier.max_sentences}s)</span>
                    )}
                  </span>
                  <span>Strategies: <b>{doneEvent.response.strategies_used.join(", ") || "—"}</b></span>
                </div>
                {doneEvent.response.validation.issues.length > 0 && (
                  <div className="mt-2 rounded-xl bg-amber-50 px-3 py-2 text-[12px] text-amber-700">
                    {doneEvent.response.validation.issues.join(" · ")}
                  </div>
                )}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {Object.entries(doneEvent.response.validation.checks).map(([k, v]) => (
                    <span
                      key={k}
                      className={[
                        "rounded-md px-2 py-0.5 text-[10px] font-semibold",
                        v ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-600",
                      ].join(" ")}
                    >
                      {v ? "✓" : "✗"} {k}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Recent logs */}
        {logs.length > 0 && (
          <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
            <h2 className="text-[14px] font-bold text-ink">Recent runs</h2>
            <div className="mt-3 space-y-2">
              {logs.map((l) => (
                <div key={l.id} className="rounded-xl border border-ink/[0.06] bg-white px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[12px] font-semibold text-ink">
                      {l.reviewer_name || "Anonymous"} · {"★".repeat(l.rating ?? 0)}
                    </span>
                    <span className="text-[10px] text-ink/40">{l.model} · {l.latency_ms}ms · {l.status}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[12px] text-ink/60">{l.generated_response}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
