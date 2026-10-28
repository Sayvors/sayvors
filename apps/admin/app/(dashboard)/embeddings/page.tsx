"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { adminFetch } from "@/lib/admin-api";

interface EmbeddingProvider {
  provider: string;
  model: string | null;
  has_key: boolean;
  enabled: boolean;
  active: boolean;
  base_url: string | null;
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
  const [modelLoading, setModelLoading] = useState<Record<string, boolean>>({});
  const [modelErrors, setModelErrors] = useState<Record<string, string | null>>({});
  // One fetch per provider per page load. Without the guard the auto-fetch
  // effect re-runs on every `data` object and hammers the provider API.
  const fetchedRef = useRef<Set<string>>(new Set());

  const fetchModels = useCallback(
    async (provider: string, apiKey?: string, baseUrl?: string) => {
      setModelLoading((prev) => ({ ...prev, [provider]: true }));
      setModelErrors((prev) => ({ ...prev, [provider]: null }));
      try {
        const qs = new URLSearchParams({ provider });
        if (apiKey) qs.set("api_key", apiKey);
        if (baseUrl) qs.set("base_url", baseUrl);
        const res = await adminFetch<{ provider: string; models: string[] }>(
          `/api/v1/admin/embeddings/models?${qs}`
        );
        setAvailableModels((prev) => ({ ...prev, [provider]: res.models }));
        return res.models;
      } catch (e) {
        // The backend answers 502 with the provider's reason; showing it is
        // the difference between "no models" and "your key is wrong".
        setModelErrors((prev) => ({
          ...prev,
          [provider]: e instanceof Error ? e.message : "Could not list models.",
        }));
        return [];
      } finally {
        setModelLoading((prev) => ({ ...prev, [provider]: false }));
      }
    },
    []
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const overview = await adminFetch<EmbeddingOverview>("/api/v1/admin/embeddings");
      setData(overview);
      setModels((prev) => {
        const next = { ...prev };
        for (const p of overview.providers) {
          // The saved model is the only value that may appear here; there is
          // no built-in default to fall back to.
          next[p.provider] = p.model ?? "";
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

  // Populate each provider's model dropdown from its live API. The ref guard
  // keeps this to one request per provider per page load: `data` is a fresh
  // object after every save, and re-fetching on every save would loop.
  // Providers with no stored key are skipped — their fetch would only paint
  // an error on a card the admin has not configured yet.
  useEffect(() => {
    if (!data) return;
    for (const p of data.providers) {
      if (fetchedRef.current.has(p.provider)) continue;
      if (!p.has_key) continue;
      fetchedRef.current.add(p.provider);
      void fetchModels(p.provider);
    }
  }, [data, fetchModels]);

  const flash = (text: string) => {
    setNotice(text);
    window.setTimeout(() => setNotice((n) => (n === text ? null : n)), 4000);
  };

  const formBody = (provider: string, extra: Record<string, unknown> = {}) => {
    const model = (models[provider] ?? "").trim();
    if (!model) {
      throw new Error("Pick a model (or type its name) before saving.");
    }
    const body: Record<string, unknown> = { model, ...extra };
    // Only Ollama exposes a base URL; sending an empty string for the other
    // providers would wipe a custom endpoint saved through the API.
    if (provider === "ollama") body.base_url = baseUrls[provider] ?? "";
    const key = (keys[provider] ?? "").trim();
    if (key) body.api_key = key;
    return body;
  };

  const save = async (provider: string, extra: Record<string, unknown> = {}) => {
    setBusy(provider);
    try {
      await adminFetch(`/api/v1/admin/embeddings/${provider}`, {
        method: "PUT",
        body: JSON.stringify(formBody(provider, extra)),
      });
      setKeys((prev) => ({ ...prev, [provider]: "" }));
      // Re-fetch this provider's list with the key that was just saved.
      fetchedRef.current.delete(provider);
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
      await adminFetch(`/api/v1/admin/embeddings/${provider}`, {
        method: "PUT",
        body: JSON.stringify(formBody(provider, { activate: true })),
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
          <strong className="text-ink/85">No embedding provider configured.</strong> Search stays
          keyword-only and new chunks are stored without vectors until you pick a provider, fetch its
          model list and save a model below.
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
                <div className="mt-1 flex items-center gap-2">
                  <input
                    type="text"
                    list={`embedding-models-${p.provider}`}
                    value={models[p.provider] ?? ""}
                    disabled={isBusy}
                    onChange={(e) => setModels((prev) => ({ ...prev, [p.provider]: e.target.value }))}
                    placeholder={modelLoading[p.provider] ? "Loading models…" : "Pick a model or type its name"}
                    aria-label={`${p.provider} embedding model`}
                    autoComplete="off"
                    className="input-field flex-1"
                  />
                  <datalist id={`embedding-models-${p.provider}`}>
                    {(availableModels[p.provider] ?? []).map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                  <button
                    onClick={() =>
                      void fetchModels(
                        p.provider,
                        keys[p.provider],
                        p.provider === "ollama" ? baseUrls[p.provider] : undefined
                      )
                    }
                    disabled={isBusy || modelLoading[p.provider]}
                    title="Fetch the live model list from the provider's API"
                    aria-label={`Fetch models from ${p.provider}`}
                    className={`shrink-0 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-50 ${FOCUS_RING}`}
                  >
                    {modelLoading[p.provider] ? "…" : "↻"}
                  </button>
                </div>
                <p className="mt-1 text-[10px] leading-relaxed text-ink/35">
                  {modelErrors[p.provider] ? (
                    <span className="text-red-600">{modelErrors[p.provider]}</span>
                  ) : modelLoading[p.provider] ? (
                    "Fetching the live model list…"
                  ) : (availableModels[p.provider]?.length ?? 0) > 0 ? (
                    `${availableModels[p.provider].length} models fetched from the provider API`
                  ) : fetchedRef.current.has(p.provider) ? (
                    "The provider returned no models — type a model name manually."
                  ) : (
                    "No model list yet — click ↻ to fetch it from the provider."
                  )}
                </p>

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
