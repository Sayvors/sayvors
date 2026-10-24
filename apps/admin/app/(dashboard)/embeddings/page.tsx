"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import { adminFetch } from "@/lib/admin-api";

interface EmbeddingProvider {
  provider: string;
  model: string | null;
  has_key: boolean;
  enabled: boolean;
  active: boolean;
  base_url: string | null;
  supported_models: string[];
}

interface EmbeddingOverview {
  providers: EmbeddingProvider[];
  active_provider: string | null;
  canonical_dimensions: number;
  chunks_total: number;
  chunks_with_vector: number;
  source: "admin" | "fallback";
}

interface TestResult {
  ok: boolean;
  provider: string | null;
  model: string | null;
  dimensions: number;
  latency_ms: number;
  detail: string;
}

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

const BRAND: Record<string, { gradient: string; initial: string; icon?: string }> = {
  gemini: { gradient: "from-[#4285F4] to-[#9b72cb]", initial: "G", icon: "googlegemini" },
  openai: { gradient: "from-zinc-800 to-black", initial: "O", icon: "openai" },
  ollama: { gradient: "from-pink-500 to-violet-600", initial: "O", icon: "ollama" },
  openrouter: { gradient: "from-[#6366F1] to-[#8B5CF6]", initial: "R", icon: "openrouter" },
  nvidia: { gradient: "from-[#76B900] to-[#5A8F00]", initial: "N", icon: "nvidia" },
};

function ProviderLogo({ provider }: { provider: string }) {
  const [failed, setFailed] = useState(false);
  const brand = BRAND[provider] ?? {
    gradient: "from-deep-violet to-magenta",
    initial: provider.slice(0, 1).toUpperCase(),
  };
  return (
    <span
      aria-hidden
      className={`flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-[2px] bg-gradient-to-br text-[18px] font-bold text-white ${brand.gradient}`}
    >
      {!failed && brand.icon ? (
        <Image
          src={`https://cdn.jsdelivr.net/npm/simple-icons@v15/icons/${brand.icon}.svg`}
          alt=""
          width={26}
          height={26}
          loading="lazy"
          onError={() => setFailed(true)}
          className="h-[26px] w-[26px] brightness-0 invert"
          unoptimized
        />
      ) : (
        brand.initial
      )}
    </span>
  );
}

export default function AdminEmbeddingsPage() {
  const [data, setData] = useState<EmbeddingOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  // Per-provider form state, so switching cards never loses a half-typed key.
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [models, setModels] = useState<Record<string, string>>({});
  const [baseUrls, setBaseUrls] = useState<Record<string, string>>({});
  const [availableModels, setAvailableModels] = useState<Record<string, string[]>>({});
  const [modelSearch, setModelSearch] = useState<Record<string, string>>({});
  const fetchModels = useCallback(async (provider: string, apiKey?: string, baseUrl?: string) => {
    try {
      const qs = new URLSearchParams({ provider });
      if (apiKey) qs.set("api_key", apiKey);
      if (baseUrl) qs.set("base_url", baseUrl);
      const res = await adminFetch<{ provider: string; models: string[] }>(`/api/v1/admin/embeddings/models?${qs}`);
      setAvailableModels((prev) => ({ ...prev, [provider]: res.models }));
      // Auto-select first model if none chosen yet
      setModels((prev) => {
        if (prev[provider]) return prev;
        const first = res.models[0];
        if (!first) return prev;
        return { ...prev, [provider]: first };
      });
    } catch {
      // Fall back to supported_models from overview
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const overview = await adminFetch<EmbeddingOverview>("/api/v1/admin/embeddings");
      setData(overview);
      setModels((prev) => {
        const next = { ...prev };
        for (const p of overview.providers) {
          if (!next[p.provider]) next[p.provider] = p.model ?? p.supported_models[0] ?? "";
        }
        return next;
      });
      setBaseUrls((prev) => {
        const next = { ...prev };
        for (const p of overview.providers) {
          if (next[p.provider] === undefined) next[p.provider] = p.base_url ?? "";
        }
        return next;
      });
      setError(null);
      // Don't auto-fetch models here — user clicks refresh per provider
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed.");
    } finally {
      setLoading(false);
    }
  }, []); // No dependencies — load only runs on mount

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!cancelled) await load();
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const flash = (text: string) => {
    setNotice(text);
    window.setTimeout(() => setNotice((n) => (n === text ? null : n)), 4000);
  };

  const save = async (provider: string, extra: Record<string, unknown> = {}) => {
    setBusy(provider);
    try {
      const key = (keys[provider] ?? "").trim();
      // The model and base URL are part of the form, so they are saved with
      // the key: a half-typed key must not be lost by clicking elsewhere.
      const body: Record<string, unknown> = {
        model: models[provider],
        base_url: baseUrls[provider] ?? "",
        ...extra,
      };
      if (key) body.api_key = key;
      await adminFetch(`/api/v1/admin/embeddings/${provider}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setKeys((prev) => ({ ...prev, [provider]: "" }));
      await load();
      flash(`${provider} embedding provider saved.`);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  };

  const clearKey = async (provider: string) => {
    if (!confirm(`Remove the stored ${provider} embedding key?`)) return;
    setBusy(provider);
    try {
      await adminFetch(`/api/v1/admin/embeddings/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ api_key: "" }),
      });
      await load();
      flash(`${provider} embedding key cleared.`);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Clear failed.");
    } finally {
      setBusy(null);
    }
  };

  const activate = async (provider: string) => {
    setBusy(provider);
    try {
      const key = (keys[provider] ?? "").trim();
      const body: Record<string, unknown> = {
        model: models[provider],
        base_url: baseUrls[provider] ?? "",
        activate: true,
      };
      if (key) body.api_key = key;
      await adminFetch(`/api/v1/admin/embeddings/${provider}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      setKeys((prev) => ({ ...prev, [provider]: "" }));
      await load();
      flash(`${provider} is now the active embedding provider.`);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Activate failed.");
    } finally {
      setBusy(null);
    }
  };

  const runTest = async (provider: string) => {
    setBusy(`${provider}:test`);
    try {
      const res = await adminFetch<TestResult>("/api/v1/admin/embeddings/test", {
        method: "POST",
        body: JSON.stringify({ provider }),
      });
      setTests((prev) => ({ ...prev, [provider]: res }));
    } catch (e) {
      setTests((prev) => ({
        ...prev,
        [provider]: {
          ok: false,
          provider,
          model: null,
          dimensions: 0,
          latency_ms: 0,
          detail: e instanceof Error ? e.message : "Test failed.",
        },
      }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Embedding providers</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            The embedding backend is configured apart from the text-generation providers. One provider is
            active at a time — vectors from two models are not comparable, so switching means the stored
            vectors have to be rebuilt.
          </p>
        </div>
        {data && (
          <div className="flex items-center gap-4 text-[11px] text-ink/45">
            <span>
              width <strong className="text-ink/70">{data.canonical_dimensions}</strong>
            </span>
            <span>
              chunks{" "}
              <strong className="text-ink/70">
                {data.chunks_with_vector}/{data.chunks_total}
              </strong>{" "}
              with a vector
            </span>
          </div>
        )}
      </div>

      {notice && (
        <div role="status" className="panel px-4 py-2.5 text-[12px] font-medium text-ink/70">
          {notice}
        </div>
      )}

      {data && data.source === "fallback" && (
        <div className="panel border-l-[3px] border-l-amber-400 px-4 py-3 text-[12px] leading-relaxed text-ink/70">
          <strong className="text-ink/85">No embedding provider configured separately.</strong> The search is
          still borrowing the text-generation keys, and no vectors are stored unless a provider answers.
          Configure one below to decouple them.
        </div>
      )}

      {error ? (
        <div className="panel p-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">{error}</p>
        </div>
      ) : loading && !data ? (
        <div className="grid gap-3 sm:grid-cols-2" aria-hidden>
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="panel h-44 animate-pulse" />
          ))}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {(data?.providers ?? []).map((p) => {
            const test = tests[p.provider];
            const isBusy = busy === p.provider || busy === `${p.provider}:test`;
            const needsKey = p.provider !== "ollama";
            return (
              <div key={p.provider} className={`panel p-4 transition ${p.active ? "" : "opacity-90"}`}>
                <div className="flex items-center gap-3">
                  <ProviderLogo provider={p.provider} />
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-1.5 text-[15px] font-bold capitalize text-ink">
                      {p.provider}
                      {p.active ? (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700">
                          active
                        </span>
                      ) : (
                        <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/45">
                          {p.has_key ? "key stored" : needsKey ? "no key" : "local"}
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-[11px] text-ink/45">
                      {p.active
                        ? "Search uses this provider."
                        : needsKey
                          ? "Not used until it is activated."
                          : "Local server — no key needed."}
                    </p>
                  </div>
                </div>

                <label className="mt-3 block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">
                  Model
                </label>
                {availableModels[p.provider] && availableModels[p.provider].length > 0 ? (
                  <div className="mt-1 space-y-1.5">
                    <input
                      type="search"
                      value={modelSearch[p.provider] ?? ""}
                      onChange={(e) => setModelSearch((prev) => ({ ...prev, [p.provider]: e.target.value }))}
                      placeholder="Filter models…"
                      className="input-field text-[11px]"
                    />
                    <div className="flex items-center gap-2">
                      <select
                        value={models[p.provider] ?? ""}
                        disabled={isBusy}
                        onChange={(e) => setModels((prev) => ({ ...prev, [p.provider]: e.target.value }))}
                        aria-label={`${p.provider} embedding model`}
                        className="input-field flex-1 cursor-pointer"
                        size={1}
                      >
                        {(availableModels[p.provider] ?? [])
                          .filter((m) => !modelSearch[p.provider] || m.toLowerCase().includes(modelSearch[p.provider].toLowerCase()))
                          .map((m) => (
                            <option key={m} value={m}>
                              {m}
                            </option>
                          ))}
                      </select>
                      <button
                        onClick={() => fetchModels(p.provider, keys[p.provider], baseUrls[p.provider])}
                        disabled={isBusy}
                        title="Re-fetch available models from the provider's API"
                        className={`shrink-0 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet ${FOCUS_RING}`}
                      >
                        ↻
                      </button>
                    </div>
                    <p className="text-[10px] text-ink/35">
                      {(availableModels[p.provider] ?? []).filter((m) => !modelSearch[p.provider] || m.toLowerCase().includes((modelSearch[p.provider] ?? "").toLowerCase())).length} of {availableModels[p.provider].length} models
                    </p>
                  </div>
                ) : (
                  <div className="mt-1 space-y-1.5">
                    <input
                      type="text"
                      value={models[p.provider] ?? ""}
                      disabled={isBusy}
                      onChange={(e) => setModels((prev) => ({ ...prev, [p.provider]: e.target.value }))}
                      placeholder="e.g. openai/text-embedding-3-small"
                      className="input-field"
                    />
                    <button
                      onClick={() => fetchModels(p.provider, keys[p.provider], baseUrls[p.provider])}
                      disabled={isBusy}
                      className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet ${FOCUS_RING}`}
                    >
                      ↻ Fetch models from API
                    </button>
                    <p className="text-[10px] text-ink/35">
                      No models found via API. Type a model name manually, or click fetch to try again.
                    </p>
                  </div>
                )}
                {availableModels[p.provider] && availableModels[p.provider].length > 0 && (
                  <p className="mt-1 text-[10px] text-ink/35">{availableModels[p.provider].length} models available</p>
                )}

                {p.provider === "ollama" && (
                  <>
                    <label className="mt-3 block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">
                      Base URL
                    </label>
                    <input
                      value={baseUrls[p.provider] ?? ""}
                      onChange={(e) => setBaseUrls((prev) => ({ ...prev, [p.provider]: e.target.value }))}
                      placeholder="http://localhost:11434"
                      autoComplete="off"
                      className="input-field mt-1"
                    />
                  </>
                )}

                {needsKey && (
                  <>
                    <label className="mt-3 block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">
                      Embedding API key
                    </label>
                    <input
                      type="password"
                      value={keys[p.provider] ?? ""}
                      onChange={(e) => setKeys((prev) => ({ ...prev, [p.provider]: e.target.value }))}
                      placeholder={p.has_key ? "Key stored — paste a new one to replace" : "Paste the embedding API key…"}
                      autoComplete="off"
                      className="input-field mt-1"
                    />
                    {p.has_key && (
                      <button
                        onClick={() => void clearKey(p.provider)}
                        disabled={isBusy}
                        className="mt-1 text-[11px] font-semibold text-ink/40 underline-offset-2 transition hover:text-red-600 hover:underline disabled:opacity-50"
                      >
                        Clear stored key
                      </button>
                    )}
                  </>
                )}

                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <button
                    onClick={() => void save(p.provider)}
                    disabled={isBusy}
                    className="btn-secondary !px-3 !py-1.5 disabled:opacity-50"
                  >
                    Save
                  </button>
                  {!p.active && (
                    <button
                      onClick={() => void activate(p.provider)}
                      disabled={isBusy}
                      className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
                    >
                      Make active
                    </button>
                  )}
                  <button
                    onClick={() => void runTest(p.provider)}
                    disabled={isBusy}
                    className="btn-secondary !px-3 !py-1.5 disabled:opacity-50"
                  >
                    Test
                  </button>
                </div>

                {test && (
                  <p
                    className={`mt-2 text-[11px] ${test.ok ? "text-emerald-600" : "text-red-600"}`}
                    role="status"
                  >
                    {test.ok ? "OK" : "Failed"} · {test.latency_ms}ms · {test.dimensions} dimensions
                    {test.detail ? ` — ${test.detail}` : ""}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
