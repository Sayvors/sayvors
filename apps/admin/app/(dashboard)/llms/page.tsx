"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

interface LlmStatus {
  provider: string;
  key_source: "database" | "none" | "disabled";
  enabled: boolean;
  has_key: boolean;
}

interface SavedModel {
  id: string;
  name: string;
  provider: string;
  api_model: string;
  enabled: boolean;
  custom: boolean;
  tested_ok: boolean | null;
  tested_at: string | null;
}

interface RemoteModel {
  id: string;
  name: string;
}

interface TestResult {
  ok: boolean;
  latency_ms: number;
  detail: string;
}

interface ModelTestResult extends TestResult {
  model_id: string;
  reply: string;
}

const SOURCE_LABEL: Record<LlmStatus["key_source"], { text: string; cls: string }> = {
  database: { text: "database", cls: "bg-deep-violet/10 text-deep-violet" },
  none: { text: "no key", cls: "bg-ink/[0.05] text-ink/50" },
  disabled: { text: "disabled", cls: "bg-red-100 text-red-700" },
};

const BRAND: Record<string, { gradient: string; initial: string; icon?: string }> = {
  groq: { gradient: "from-[#f55036] to-[#b91c1c]", initial: "G" },
  openai: { gradient: "from-zinc-800 to-black", initial: "O", icon: "openai" },
  gemini: { gradient: "from-[#4285F4] to-[#9b72cb]", initial: "G", icon: "googlegemini" },
  grok: { gradient: "from-zinc-800 to-black", initial: "X" },
  kimi: { gradient: "from-zinc-700 to-black", initial: "K" },
  deepseek: { gradient: "from-[#4D6BFE] to-[#1e40af]", initial: "D", icon: "deepseek" },
  ollama: { gradient: "from-pink-500 to-violet-600", initial: "O", icon: "ollama" },
  qwen: { gradient: "from-[#6D28D9] to-[#1e3a8a]", initial: "Q" },
};

const ADD_PROVIDERS = [
  { id: "openai", label: "OpenAI" },
  { id: "gemini", label: "Gemini" },
  { id: "groq", label: "Groq" },
  { id: "qwen", label: "Qwen" },
  { id: "kimi", label: "Kimi" },
];

const PROVIDER_API_URL: Record<string, string> = {
  openai: "https://api.openai.com/v1",
  gemini: "https://generativelanguage.googleapis.com/v1beta",
  groq: "https://api.groq.com/openai/v1",
  qwen: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  kimi: "https://api.moonshot.cn/v1",
};

function ProviderLogo({ provider }: { provider: string }) {
  const [failed, setFailed] = useState(false);
  const brand = BRAND[provider] ?? { gradient: "from-deep-violet to-magenta", initial: provider.slice(0, 1).toUpperCase() };
  return (
    <span
      aria-hidden
      className={`flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-[6px] bg-gradient-to-br text-[18px] font-bold text-white shadow-md ${brand.gradient}`}
    >
      {!failed && brand.icon ? (
        <img
          src={`https://cdn.jsdelivr.net/npm/simple-icons@v15/icons/${brand.icon}.svg`}
          alt=""
          width={26}
          height={26}
          loading="lazy"
          onError={() => setFailed(true)}
          className="h-[26px] w-[26px] brightness-0 invert"
        />
      ) : (
        brand.initial
      )}
    </span>
  );
}

export default function AdminLlmsPage() {
  const [items, setItems] = useState<LlmStatus[]>([]);
  const [savedModels, setSavedModels] = useState<SavedModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult>>({});
  const [modelTests, setModelTests] = useState<Record<string, ModelTestResult>>({});
  const [notice, setNotice] = useState<string | null>(null);

  // Add-model flow state.
  const [adding, setAdding] = useState(false);
  const [addProvider, setAddProvider] = useState("");
   const [addApiKey, setAddApiKey] = useState("");
   const [remoteModels, setRemoteModels] = useState<RemoteModel[]>([]);
   const [remoteLoading, setRemoteLoading] = useState(false);
   const [remoteError, setRemoteError] = useState<string | null>(null);
   const [addError, setAddError] = useState<string | null>(null);
  const [addRemoteId, setAddRemoteId] = useState("");
  const [addName, setAddName] = useState("");
  const [addApi, setAddApi] = useState("");
  const [addApiUrl, setAddApiUrl] = useState("");
  const [addCtx, setAddCtx] = useState("32000");
  const [addMax, setAddMax] = useState("4096");
  const [apiCache, setApiCache] = useState<Record<string, RemoteModel[]>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [providers, models] = await Promise.all([
        adminFetch<LlmStatus[]>("/api/v1/admin/llm"),
        adminFetch<SavedModel[]>("/api/v1/admin/models"),
      ]);
      setItems(providers);
      setSavedModels(models);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed.");
    } finally {
      setLoading(false);
    }
  }, []);

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

  const saveKey = async (provider: string) => {
    if (!keyInput.trim()) return;
    setBusy(provider);
    try {
      await adminFetch(`/api/v1/admin/llm/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ api_key: keyInput.trim() }),
      });
      setKeyInput("");
      setEditing(null);
      await load();
      flash(`${provider} key stored in database.`);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  };

  const clearKey = async (provider: string) => {
    if (!confirm(`Remove the stored ${provider} key? The provider goes dark until a new key is added.`)) return;
    setBusy(provider);
    try {
      await adminFetch(`/api/v1/admin/llm/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ api_key: "" }),
      });
      await load();
      flash(`${provider} key cleared.`);
    } catch (e) {
      flash(e instanceof Error ? e.message : "Clear failed.");
    } finally {
      setBusy(null);
    }
  };

  const toggleEnabled = async (provider: string, enabled: boolean) => {
    setBusy(provider);
    try {
      await adminFetch(`/api/v1/admin/llm/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      await load();
    } catch (e) {
      flash(e instanceof Error ? e.message : "Toggle failed.");
    } finally {
      setBusy(null);
    }
  };

  const runTest = async (provider: string) => {
    setBusy(`${provider}:test`);
    try {
      const res = await adminFetch<TestResult>(`/api/v1/admin/llm/${provider}/test`, {
        method: "POST",
      });
      setTests((prev) => ({ ...prev, [provider]: res }));
    } catch (e) {
      setTests((prev) => ({
        ...prev,
        [provider]: { ok: false, latency_ms: 0, detail: e instanceof Error ? e.message : "Test failed." },
      }));
    } finally {
      setBusy(null);
    }
  };

  const runTestAll = async () => {
    setBusy("all:test");
    try {
      for (const p of items.filter((p) => p.has_key)) {
        try {
          const res = await adminFetch<TestResult>(`/api/v1/admin/llm/${p.provider}/test`, {
            method: "POST",
          });
          setTests((prev) => ({ ...prev, [p.provider]: res }));
        } catch (e) {
          setTests((prev) => ({
            ...prev,
            [p.provider]: { ok: false, latency_ms: 0, detail: e instanceof Error ? e.message : "Test failed." },
          }));
        }
      }
    } finally {
      setBusy(null);
    }
  };

  const fetchRemote = async (provider: string, apiUrl: string, apiKey?: string) => {
    const cacheKey = apiKey ? `${provider}:${apiKey.slice(-8)}` : provider;
    if (apiCache[cacheKey]) {
      setRemoteModels(apiCache[cacheKey]);
      setAddRemoteId("");
      return;
    }
    setRemoteLoading(true);
    setRemoteError(null);
    setRemoteModels([]);
    setAddRemoteId("");
    try {
      const qs = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : "";
      const list = await adminFetch<RemoteModel[]>(
        `/api/v1/admin/llm/${provider}/remote-models${qs}`
      );
      setRemoteModels(list);
      setApiCache((prev) => ({ ...prev, [cacheKey]: list }));
      if (list.length === 0) setRemoteError("Provider returned no models.");
    } catch (e) {
      setRemoteError(e instanceof Error ? e.message : "Could not list models.");
    } finally {
      setRemoteLoading(false);
    }
  };

  const pickRemote = (id: string) => {
    setAddRemoteId(id);
    const found = remoteModels.find((m) => m.id === id);
    // Pre-fill display + API names; admin edits before saving.
    const apiName = id.includes(":") ? id.split(":").slice(1).join(":") : id;
    setAddName(found?.name ?? apiName);
    setAddApi(found ? apiName : "");
  };

  const createModel = async () => {
    if (!addProvider || !addRemoteId.trim() || !addName.trim() || !addApi.trim()) {
      flash("Pick a provider, choose a model, and confirm the names.");
      return;
    }
    setBusy("models:add");
    try {
      // Save the API key first if one was typed.
      if (addApiKey.trim()) {
        await adminFetch(`/api/v1/admin/llm/${addProvider}`, {
          method: "PUT",
          body: JSON.stringify({ api_key: addApiKey.trim() }),
        });
      }
      await adminFetch(`/api/v1/admin/llm/models`, {
        method: "POST",
        body: JSON.stringify({
          id: addRemoteId.trim(),
          name: addName.trim(),
          provider: addProvider,
          api_model: addApi.trim(),
          api_url: addApiUrl.trim() || undefined,
          context_window: Math.max(1024, Number(addCtx) || 32000),
          max_output: Math.max(128, Number(addMax) || 4096),
          supports_stream: true,
        }),
      });
      setAdding(false);
      setAddProvider("");
      setAddApiKey("");
      setRemoteModels([]);
      setAddRemoteId("");
      setAddApiUrl("");
      setApiCache({});
      await load();
      flash("Model saved — tenants can now select it.");
    } catch (e) {
      setAddError(e instanceof Error ? e.message : "Add failed.");
      flash(e instanceof Error ? e.message : "Add failed.");
    } finally {
      setBusy(null);
    }
  };

  const toggleSavedModel = async (provider: string, modelId: string, enabled: boolean) => {
    const key = `saved:${modelId}`;
    setBusy(key);
    try {
      await adminFetch(`/api/v1/admin/llm/${provider}/models/${encodeURIComponent(modelId)}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      await load();
    } catch (e) {
      flash(e instanceof Error ? e.message : "Toggle failed.");
    } finally {
      setBusy(null);
    }
  };

  const testSavedModel = async (provider: string, modelId: string) => {
    const key = `saved:${modelId}:test`;
    setBusy(key);
    try {
      const res = await adminFetch<ModelTestResult>(
        `/api/v1/admin/llm/${provider}/models/${encodeURIComponent(modelId)}/test`,
        { method: "POST" }
      );
      setModelTests((prev) => ({ ...prev, [modelId]: res }));
      await load();
    } catch (e) {
      setModelTests((prev) => ({
        ...prev,
        [modelId]: { model_id: modelId, ok: false, latency_ms: 0, detail: e instanceof Error ? e.message : "Test failed.", reply: "" },
      }));
    } finally {
      setBusy(null);
    }
  };

  const deleteSavedModel = async (provider: string, modelId: string) => {
    if (!confirm(`Delete custom model ${modelId}?`)) return;
    setBusy(`saved:${modelId}:delete`);
    try {
      await adminFetch(`/api/v1/admin/llm/${provider}/models/${encodeURIComponent(modelId)}`, {
        method: "DELETE",
      });
      await load();
      flash("Model deleted.");
    } catch (e) {
      flash(e instanceof Error ? e.message : "Delete failed.");
    } finally {
      setBusy(null);
    }
  };

  const keyedProviders = items.filter((p) => p.has_key);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">LLM providers</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            Keys stored here (encrypted) are the single source of truth. Key values are never displayed back.
          </p>
        </div>
        <button
          onClick={() => void runTestAll()}
          disabled={busy !== null || loading}
          title="Probe every enabled provider with a key (free list calls)"
          className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
        >
          {busy === "all:test" ? "Testing…" : "Test all"}
        </button>
      </div>

      {notice && (
        <div role="status" className="rounded-xl border border-deep-violet/20 bg-white px-4 py-2.5 text-[12px] font-medium text-ink/70">
          {notice}
        </div>
      )}

      {error ? (
        <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">{error}</p>
        </div>
      ) : loading && items.length === 0 ? (
        <div className="grid gap-3 sm:grid-cols-2" aria-hidden>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-32 animate-pulse rounded-[6px] border-2 border-white bg-white/60" />
          ))}
        </div>
      ) : keyedProviders.length === 0 ? (
        <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[14px] font-semibold text-ink/70">No providers with keys yet</p>
          <p className="mt-1 text-[12px] text-ink/45">
            Add a provider key above to get started — models appear once a key is stored.
          </p>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {keyedProviders.map((p) => {
            const src = SOURCE_LABEL[p.key_source];
            const test = tests[p.provider];
            const isBusy = busy === p.provider || busy === `${p.provider}:test`;
            return (
              <div
                key={p.provider}
                className={`rounded-[6px] border-2 bg-white/80 p-4 backdrop-blur-sm transition ${
                  p.enabled ? "border-white hover:shadow-lg hover:shadow-deep-violet/[0.08]" : "border-ink/[0.06] opacity-75"
                }`}
              >
                <div className="flex items-center gap-3">
                  <ProviderLogo provider={p.provider} />
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-1.5 text-[15px] font-bold capitalize text-ink">
                      {p.provider}
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${src.cls}`}>
                        {src.text}
                      </span>
                      {!p.enabled && (
                        <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase text-ink/45">
                          off
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-[11px] text-ink/45">Key configured</p>
                  </div>
                  <select
                    value={p.enabled ? "enabled" : "disabled"}
                    disabled={isBusy}
                    onChange={(e) => void toggleEnabled(p.provider, e.target.value === "enabled")}
                    aria-label={`${p.provider} status`}
                    className={`ml-auto shrink-0 cursor-pointer rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[11px] font-bold outline-none transition focus:border-deep-violet/30 disabled:opacity-50 ${
                      p.enabled ? "text-emerald-600" : "text-ink/40"
                    }`}
                  >
                    <option value="enabled">Enabled</option>
                    <option value="disabled">Disabled</option>
                  </select>
                </div>

                {editing === p.provider ? (
                  <div className="mt-3 flex gap-2">
                    <input
                      type="password"
                      value={keyInput}
                      onChange={(e) => setKeyInput(e.target.value)}
                      placeholder="Paste new API key…"
                      autoComplete="off"
                      className="input-field flex-1"
                    />
                    <button
                      onClick={() => void saveKey(p.provider)}
                      disabled={isBusy || !keyInput.trim()}
                      className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => {
                        setEditing(null);
                        setKeyInput("");
                      }}
                      className="btn-secondary !px-3 !py-1.5"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-ink/[0.05] pt-3">
                    <button
                      onClick={() => {
                        setEditing(p.provider);
                        setKeyInput("");
                      }}
                      disabled={isBusy}
                      className="btn-secondary !px-3 !py-1.5 disabled:opacity-50"
                    >
                      Replace key
                    </button>
                    <button
                      onClick={() => void clearKey(p.provider)}
                      disabled={isBusy}
                      className="rounded-xl px-3 py-1.5 text-[11px] font-semibold text-ink/40 transition hover:text-coral disabled:opacity-50"
                    >
                      Clear
                    </button>
                    <button
                      onClick={() => void runTest(p.provider)}
                      disabled={isBusy}
                      className="ml-auto rounded-xl bg-emerald-500 px-3 py-1.5 text-[11px] font-bold text-white shadow-sm transition hover:bg-emerald-600 disabled:opacity-50"
                    >
                      Test
                    </button>
                  </div>
                )}

                {test && (
                  <p className={`mt-2 text-[11px] font-medium ${test.ok ? "text-emerald-600" : "text-coral"}`}>
                    {test.ok ? `✓ ${test.detail} (${test.latency_ms}ms)` : `✗ ${test.detail}`}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <section className="rounded-[6px] border-2 border-white bg-white/80 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[16px] font-bold text-ink">Models</h2>
            <p className="mt-0.5 text-[12px] text-ink/50">
              Only saved models reach tenants. Add one from a provider&apos;s live list, test it, keep it on.
            </p>
          </div>
          {!adding && (
            <button onClick={() => setAdding(true)} className="btn-primary !px-3 !py-1.5">
              + Add model
            </button>
          )}
        </div>

        {adding && (
          <div className="mt-3 space-y-3 rounded-xl border border-dashed border-ink/[0.12] p-4">
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">1 · Provider</label>
              <select
                value={addProvider}
                onChange={(e) => {
                  const p = e.target.value;
                  setAddProvider(p);
                  setRemoteModels([]);
                  setAddRemoteId("");
                  setRemoteError(null);
                  setAddApiUrl(PROVIDER_API_URL[p] ?? "");
                  if (p && addApiKey.trim()) void fetchRemote(p, PROVIDER_API_URL[p] ?? "", addApiKey.trim());
                }}
                className="input-field"
              >
                <option value="">Select provider…</option>
                {ADD_PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>{p.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">2 · API key</label>
              <input
                type="password"
                value={addApiKey}
                onChange={(e) => setAddApiKey(e.target.value)}
                placeholder="sk-… or gsk-… — typed here, saved to DB on Add"
                autoComplete="off"
                className="input-field"
              />
              {addProvider && items.find((p) => p.provider === addProvider)?.has_key && (
                <p className="mt-0.5 text-[10px] text-emerald-600">
                  Key already saved for {addProvider} — leave blank to use it.
                </p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">3 · API endpoint</label>
              <input
                value={addApiUrl}
                onChange={(e) => setAddApiUrl(e.target.value)}
                placeholder="https://api.example.com/v1"
                className="input-field font-mono text-[11px]"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">4 · Fetch models</label>
              <div className="flex gap-2">
                 <button
                   type="button"
                   disabled={!addProvider || (!addApiKey.trim() && !items.find((p) => p.provider === addProvider)?.has_key) || remoteLoading}
                   onClick={() => {
                     if (addProvider) void fetchRemote(addProvider, addApiUrl, addApiKey.trim() || undefined);
                   }}
                  className="btn-secondary !px-3 !py-1.5 disabled:opacity-50"
                >
                  {remoteLoading ? "Loading…" : "Fetch models"}
                </button>
                {!addProvider && <span className="text-[11px] text-ink/40 self-center">Pick a provider first</span>}
                {addProvider && !addApiKey.trim() && !items.find((p) => p.provider === addProvider)?.has_key && <span className="text-[11px] text-ink/40 self-center">Enter an API key or save one first</span>}
              </div>
              {remoteError && <p className="mt-1 text-[11px] text-coral">{remoteError}</p>}
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">5 · Model from the list</label>
              <select
                value={addRemoteId}
                disabled={!addProvider || remoteLoading || remoteModels.length === 0}
                onChange={(e) => pickRemote(e.target.value)}
                className="input-field disabled:opacity-50"
              >
                <option value="">{remoteLoading ? "Loading…" : remoteModels.length > 0 ? "Select model…" : "No models yet — fetch first"}</option>
                {remoteModels.map((m) => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div className="col-span-2">
                <label className="mb-1 block text-[11px] font-semibold text-ink/50">Display name</label>
                <input value={addName} onChange={(e) => setAddName(e.target.value)} placeholder="My Custom Model" className="input-field" />
              </div>
              <div className="col-span-2">
                <label className="mb-1 block text-[11px] font-semibold text-ink/50">Provider model name</label>
                <input value={addApi} onChange={(e) => setAddApi(e.target.value)} placeholder="exact api model id" className="input-field font-mono" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-ink/50">Context window</label>
                <input value={addCtx} onChange={(e) => setAddCtx(e.target.value)} inputMode="numeric" className="input-field" />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-ink/50">Max output</label>
                <input value={addMax} onChange={(e) => setAddMax(e.target.value)} inputMode="numeric" className="input-field" />
              </div>
            </div>
            <div className="flex gap-2">
               {addError && <p className="text-[11px] text-coral">{addError}</p>}
               <button onClick={() => void createModel()} disabled={busy !== null} className="btn-primary !px-4 !py-2 disabled:opacity-50">
                 {busy === "models:add" ? "Saving…" : "Add model"}
               </button>
               <button onClick={() => { setAdding(false); setAddError(null); }} className="btn-secondary !px-4 !py-2">
                 Cancel
               </button>
             </div>
          </div>
        )}

        <ul className="mt-3 space-y-2">
          {savedModels.length === 0 ? (
            <li className="rounded-xl bg-ink/[0.02] p-4 text-center text-[12px] text-ink/40">
              No saved models yet — tenants see nothing until you add the first one.
            </li>
          ) : (
            savedModels.map((m) => {
              const mt = modelTests[m.id];
              const mbusy = (busy ?? "").startsWith(`saved:${m.id}`);
              return (
                <li key={m.id} className="rounded-xl bg-ink/[0.02] p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink" title={m.id}>
                      {m.name}
                      <span className="ml-1.5 font-mono text-[10px] font-normal text-ink/35">{m.id}</span>
                      {m.custom && (
                        <span className="ml-1.5 rounded bg-deep-violet/10 px-1.5 py-px text-[9px] font-bold uppercase text-deep-violet">
                          custom
                        </span>
                      )}
                    </span>
                    <span className="rounded bg-ink/[0.05] px-1.5 py-0.5 text-[10px] font-semibold capitalize text-ink/50">
                      {m.provider}
                    </span>
                    {m.tested_ok === true && (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[9px] font-bold uppercase text-emerald-700" title={m.tested_at ?? ""}>
                        tested ✓
                      </span>
                    )}
                    {m.tested_ok === false && (
                      <span className="rounded-full bg-red-100 px-2 py-0.5 text-[9px] font-bold uppercase text-red-700" title={m.tested_at ?? ""}>
                        failed
                      </span>
                    )}
                    <select
                      value={m.enabled ? "enabled" : "disabled"}
                      disabled={mbusy}
                      onChange={(e) => void toggleSavedModel(m.provider, m.id, e.target.value === "enabled")}
                      aria-label={`${m.id} status`}
                      className="shrink-0 cursor-pointer rounded-lg border border-ink/[0.08] bg-white px-1.5 py-1 text-[10px] font-bold outline-none focus:border-deep-violet/30 disabled:opacity-50"
                    >
                      <option value="enabled">On</option>
                      <option value="disabled">Off</option>
                    </select>
                    <button
                      onClick={() => void testSavedModel(m.provider, m.id)}
                      disabled={mbusy}
                      className="shrink-0 rounded-lg bg-emerald-500 px-2 py-1 text-[10px] font-bold text-white transition hover:bg-emerald-600 disabled:opacity-50"
                    >
                      Test
                    </button>
                    {m.custom && (
                      <button
                        onClick={() => void deleteSavedModel(m.provider, m.id)}
                        disabled={mbusy}
                        aria-label={`Delete ${m.id}`}
                        className="shrink-0 rounded-lg px-1.5 py-1 text-[10px] font-bold text-ink/30 transition hover:text-coral disabled:opacity-50"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                  {mt && (
                    <p className={`mt-1.5 text-[10px] font-medium ${mt.ok ? "text-emerald-600" : "text-coral"}`}>
                      {mt.ok ? `✓ ${mt.detail} (${mt.latency_ms}ms)` : `✗ ${mt.detail}`}
                      {mt.ok && mt.reply && <span className="text-ink/45"> — “{mt.reply}”</span>}
                    </p>
                  )}
                </li>
              );
            })
          )}
        </ul>
      </section>
    </div>
  );
}
