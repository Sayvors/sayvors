"use client";

import { useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import { askDatabank, listDocuments, searchRag, type AskResponse } from "@/lib/api-rag";

interface Hit {
  content: string;
  score: number;
  document_id: string;
  metadata_?: Record<string, unknown> | null;
}

export default function RetrievalTab({ databankId }: { databankId: string }) {
  const [mode, setMode] = useState<"search" | "ask">("search");
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [searching, setSearching] = useState(false);
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState<number | null>(null);

  /* Ask (agentic) state */
  const [asking, setAsking] = useState(false);
  const [askResult, setAskResult] = useState<AskResponse | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  const [showTrace, setShowTrace] = useState(false);

  async function handleSearch() {
    if (!query.trim()) return;
    if (mode === "ask") {
      await handleAsk();
      return;
    }
    setSearching(true);
    setError(null);
    setHits(null);
    const started = Date.now();
    try {
      const [res, docs] = await Promise.all([
        searchRag(databankId, query.trim(), topK),
        listDocuments(databankId).catch(() => ({ documents: [] })),
      ]);
      const map: Record<string, string> = {};
      for (const d of docs.documents ?? []) map[d.id] = d.filename;
      setNames(map);
      setHits(res.chunks ?? []);
      setElapsed(Date.now() - started);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed.");
    } finally {
      setSearching(false);
    }
  }

  async function handleAsk() {
    setAsking(true);
    setAskError(null);
    setAskResult(null);
    try {
      const res = await askDatabank(databankId, query.trim());
      setAskResult(res);
    } catch (e) {
      setAskError(e instanceof Error ? e.message.slice(0, 300) : "Ask failed.");
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-[13px] font-bold text-ink">Test retrieval accuracy</p>
          <p className="text-[11px] text-ink/45">
            {mode === "search"
              ? "Ask like your customers would. Scores blend vector similarity with keyword match."
              : "Gemini reasons over 6 tools (docs + live databases) and answers with citations."}
          </p>
        </div>
        <div className="flex rounded-xl bg-ink/[0.04] p-0.5" role="tablist" aria-label="Retrieval mode">
          {(["search", "ask"] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-[10px] px-3 py-1.5 text-[12px] font-bold transition ${
                mode === m ? "bg-white text-deep-violet shadow-sm" : "text-ink/45 hover:text-ink/70"
              }`}
            >
              {m === "search" ? "Chunks" : "Ask AI"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSearch();
          }}
          placeholder="e.g. How do I reset my password?"
          className="flex-1 rounded-xl border-2 border-white bg-ink/[0.03] px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40"
        />
        <div className="flex items-center gap-2">
          {mode === "search" && (
            <>
              <label htmlFor="topk" className="whitespace-nowrap text-[11px] font-semibold text-ink/45">
                Top {topK}
              </label>
              <input
                id="topk"
                type="range"
                min={1}
                max={20}
                value={topK}
                onChange={(e) => setTopK(Number(e.target.value))}
                className="w-24 accent-deep-violet"
              />
            </>
          )}
          <button
            onClick={handleSearch}
            disabled={searching || asking || !query.trim()}
            className="flex items-center gap-2 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90 disabled:opacity-40"
          >
            {(searching || asking) && <LogoLoader size={14} />}
            {mode === "search" ? "Search" : "Ask"}
          </button>
        </div>
      </div>

      {mode === "ask" ? (
        <AskPanel
          asking={asking}
          error={askError}
          result={askResult}
          showTrace={showTrace}
          onToggleTrace={() => setShowTrace((v) => !v)}
        />
      ) : (
        <>
          {error && <p role="alert" className="break-words text-[12px] font-medium text-coral">{error}</p>}

          {searching && (
            <div className="flex justify-center py-8" aria-hidden>
              <LogoLoader size={36} />
            </div>
          )}

          {hits && !searching && (
        <div>
          <p className="mb-2 text-[11px] text-ink/45">
            {hits.length} chunk{hits.length === 1 ? "" : "s"}
            {elapsed !== null ? ` in ${elapsed}ms` : ""}
          </p>
          {hits.length === 0 ? (
            <div className="rounded-xl bg-ink/[0.02] px-4 py-8 text-center">
              <p className="text-[13px] font-semibold text-ink/40">No relevant chunks found</p>
              <p className="mt-1 text-[11px] text-ink/30">Try different wording, or process more documents first.</p>
            </div>
          ) : (
            <ol className="space-y-2">
              {hits.map((h, i) => (
                <li key={`${h.document_id}-${i}`} className="rounded-xl border-2 border-white bg-white/60 p-3.5">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-deep-violet text-[10px] font-bold text-white">
                      {i + 1}
                    </span>
                    <span className="truncate text-[11px] font-semibold text-ink/60">
                      {names[h.document_id] ?? h.document_id.slice(0, 8)}
                    </span>
                    <span
                      className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold tabular-nums ${
                        h.score >= 0.7
                          ? "bg-emerald-100 text-emerald-700"
                          : h.score >= 0.4
                            ? "bg-amber-100 text-amber-700"
                            : "bg-ink/[0.05] text-ink/45"
                      }`}
                      title="Hybrid relevance score"
                    >
                      {(h.score * 100).toFixed(0)}%
                    </span>
                  </div>
                  <p className="line-clamp-4 text-[12px] leading-relaxed text-ink/70">{h.content}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
        </>
      )}
    </div>
  );
}

function AskPanel({
  asking,
  error,
  result,
  showTrace,
  onToggleTrace,
}: {
  asking: boolean;
  error: string | null;
  result: import("@/lib/api-rag").AskResponse | null;
  showTrace: boolean;
  onToggleTrace: () => void;
}) {
  return (
    <div>
      {error && <p role="alert" className="break-words text-[12px] font-medium text-coral">{error}</p>}

      {asking && (
        <div className="flex flex-col items-center gap-2 py-8" aria-hidden>
          <LogoLoader size={40} />
          <p className="text-[11px] text-ink/40">Agent is reasoning over your sources…</p>
        </div>
      )}

      {result && !asking && (
        <div className="space-y-3">
          <div className="rounded-xl border-2 border-deep-violet/15 bg-white/70 p-4">
            <p className="whitespace-pre-line text-[13px] leading-relaxed text-ink">{result.answer}</p>
            <p className="mt-2 text-[10px] text-ink/35">
              {result.model} · {result.steps_used} step{result.steps_used === 1 ? "" : "s"}
            </p>
          </div>

          {result.citations.length > 0 && (
            <div>
              <p className="mb-1.5 text-[11px] font-bold text-ink/55">Sources</p>
              <div className="flex flex-wrap gap-1.5">
                {result.citations.map((c, i) => (
                  <span
                    key={`${c.source}-${i}`}
                    title={c.detail}
                    className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${
                      c.kind === "live"
                        ? "bg-emerald-100 text-emerald-700"
                        : "bg-deep-violet/[0.07] text-deep-violet"
                    }`}
                  >
                    {c.kind === "live" ? "● live" : "◈ doc"} · {c.source.replace(/^(live|snapshot):/, "").slice(0, 40)}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div>
            <button
              onClick={onToggleTrace}
              aria-expanded={showTrace}
              className="text-[11px] font-semibold text-deep-violet hover:underline"
            >
              {showTrace ? "Hide agent trace" : `Show agent trace (${result.trace.length} steps)`}
            </button>
            {showTrace && (
              <ol className="mt-2 space-y-1.5">
                {result.trace.map((s, i) => (
                  <li key={i} className="rounded-lg bg-ink/[0.03] px-3 py-2 font-mono text-[10.5px] leading-relaxed text-ink/60">
                    <span className="font-bold text-deep-violet">step {s.step}</span>
                    {s.tool ? (
                      <>
                        {" "}→ <span className="font-bold">{s.tool}</span>
                        <span className="text-ink/40"> {JSON.stringify(s.args).slice(0, 160)}</span>
                        <span className="text-ink/30"> · {s.ms}ms</span>
                        <span className="mt-0.5 block whitespace-pre-line font-sans">{s.observation.slice(0, 400)}</span>
                      </>
                    ) : (
                      <span> {s.observation}</span>
                    )}
                    {s.thought && (
                      <span className="mt-0.5 block italic text-ink/40">“{s.thought.slice(0, 200)}”</span>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
