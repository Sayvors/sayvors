"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";

interface Provider {
  provider: string;
  key_source: string;
  enabled: boolean;
  has_key: boolean;
  models: Model[];
}
interface Model {
  id: string;
  name: string;
  enabled: boolean;
  tested_ok: boolean | null;
  tested_at: string | null;
  custom: boolean;
}
interface TestResult {
  ok: boolean;
  latency_ms?: number;
  detail?: string;
}
interface RemoteModel {
  id: string;
  name: string;
}

export default function AdminModelsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [keyDrafts, setKeyDrafts] = useState<Record<string, string>>({});
  const [testResults, setTestResults] = useState<Record<string, TestResult>>({});
  const [remote, setRemote] = useState<Record<string, RemoteModel[]>>({});
  const [showAdd, setShowAdd] = useState<string | null>(null);
  const [form, setForm] = useState({ id: "", name: "", api_model: "", context_window: 32000, max_output: 4096 });

  const load = useCallback(async () => {
    try {
      const data = await adminFetch<Provider[]>("/api/v1/admin/llm");
      setProviders(data ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load providers.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function saveKey(provider: string) {
    const key = (keyDrafts[provider] ?? "").trim();
    if (!key) return;
    setBusy(`${provider}:key`);
    try {
      await adminFetch(`/api/v1/admin/llm/${provider}`, {
        method: "PUT",
        body: JSON.stringify({ api_key: key }),
      });
      setKeyDrafts((prev) => ({ ...prev, [provider]: "" }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save key.");
    } finally {
      setBusy(null);
    }
  }

  async function testProvider(provider: string) {
    setBusy(`${provider}:test`);
    try {
      const r = await adminFetch<TestResult>(`/api/v1/admin/llm/${provider}/test`, { method: "POST" });
      setTestResults((prev) => ({ ...prev, [provider]: r }));
    } catch (e) {
      setTestResults((prev) => ({ ...prev, [provider]: { ok: false, detail: e instanceof Error ? e.message : "failed" } }));
    } finally {
      setBusy(null);
    }
  }

  async function toggleModel(provider: string, modelId: string, enabled: boolean) {
    setBusy(`${modelId}:toggle`);
    try {
      await adminFetch(`/api/v1/admin/llm/${provider}/models/${encodeURIComponent(modelId)}`, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update model.");
    } finally {
      setBusy(null);
    }
  }

  async function testModel(provider: string, modelId: string) {
    setBusy(`${modelId}:test`);
    try {
      const r = await adminFetch<{ ok: boolean; detail?: string }>(
        `/api/v1/admin/llm/${provider}/models/${encodeURIComponent(modelId)}/test`,
        { method: "POST" },
      );
      setTestResults((prev) => ({ ...prev, [modelId]: { ok: r.ok, detail: r.detail } }));
    } catch (e) {
      setTestResults((prev) => ({ ...prev, [modelId]: { ok: false, detail: e instanceof Error ? e.message : "failed" } }));
    } finally {
      setBusy(null);
    }
  }

  async function deleteModel(provider: string, modelId: string) {
    setBusy(`${modelId}:del`);
    try {
      await adminFetch(`/api/v1/admin/llm/${provider}/models/${encodeURIComponent(modelId)}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete model.");
    } finally {
      setBusy(null);
    }
  }

  async function fetchRemote(provider: string) {
    setBusy(`${provider}:remote`);
    try {
      const list = await adminFetch<RemoteModel[]>(`/api/v1/admin/llm/${provider}/remote-models`);
      setRemote((prev) => ({ ...prev, [provider]: list ?? [] }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not list remote models.");
    } finally {
      setBusy(null);
    }
  }

  async function addModel(provider: string) {
    if (!form.id.trim() || !form.name.trim() || !form.api_model.trim()) return;
    setBusy(`${provider}:add`);
    try {
      await adminFetch("/api/v1/admin/llm/models", {
        method: "POST",
        body: JSON.stringify({
          id: `${provider}:${form.id.trim()}`,
          name: form.name.trim(),
          provider,
          api_model: form.api_model.trim(),
          context_window: form.context_window,
          max_output: form.max_output,
          enabled: true,
        }),
      });
      setShowAdd(null);
      setForm({ id: "", name: "", api_model: "", context_window: 32000, max_output: 4096 });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add model.");
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;

  return (
    <div className="space-y-5">
      {error && <p className="rounded-xl bg-coral/10 px-4 py-3 text-[12px] font-medium text-coral">{error}</p>}
      <p className="text-[12px] text-ink/50">
        Keys and models here drive every AI feature tenants use. A provider without a working key = broken AI for tenants on it. Facts only: save, test, read the result.
      </p>
      {providers.map((p) => (
        <section key={p.provider} className="rounded-2xl border border-white bg-white/80 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-[15px] font-bold capitalize text-ink">{p.provider}</h2>
              <p className="mt-0.5 text-[11px] text-ink/45">
                Key: <span className={`font-bold ${p.has_key ? "text-emerald-600" : "text-coral"}`}>{p.has_key ? `present (${p.key_source})` : "MISSING"}</span>
                {" · "}
                <span className={`font-bold ${p.enabled ? "text-emerald-600" : "text-coral"}`}>{p.enabled ? "enabled" : "disabled"}</span>
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="password"
                value={keyDrafts[p.provider] ?? ""}
                onChange={(e) => setKeyDrafts((prev) => ({ ...prev, [p.provider]: e.target.value }))}
                placeholder={p.has_key ? "Replace key…" : "Paste API key…"}
                className="input-field w-48"
                autoComplete="off"
              />
              <button
                onClick={() => void saveKey(p.provider)}
                disabled={busy !== null || !(keyDrafts[p.provider] ?? "").trim()}
                className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-40"
              >
                {busy === `${p.provider}:key` ? "Saving…" : "Save key"}
              </button>
              <button
                onClick={() => void testProvider(p.provider)}
                disabled={busy !== null}
                className="rounded-lg border border-ink/10 px-3 py-1.5 text-[11px] font-bold text-ink/60 disabled:opacity-40"
              >
                {busy === `${p.provider}:test` ? "Testing…" : "Test"}
              </button>
              <button
                onClick={() => void fetchRemote(p.provider)}
                disabled={busy !== null}
                className="rounded-lg border border-ink/10 px-3 py-1.5 text-[11px] font-bold text-ink/60 disabled:opacity-40"
              >
                {busy === `${p.provider}:remote` ? "Loading…" : "List remote models"}
              </button>
            </div>
          </div>
          {testResults[p.provider] && (
            <p className={`mt-2 rounded-lg px-3 py-2 text-[12px] font-medium ${testResults[p.provider].ok ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
              {testResults[p.provider].ok ? "Provider OK" : "Provider FAILED"}
              {testResults[p.provider].latency_ms ? ` — ${testResults[p.provider].latency_ms}ms` : ""}
              {testResults[p.provider].detail ? ` — ${testResults[p.provider].detail}` : ""}
            </p>
          )}

          <div className="mt-4 overflow-hidden rounded-xl border border-ink/[0.05]">
            <table className="w-full text-left text-[12.5px]">
              <thead>
                <tr className="bg-ink/[0.02] text-[10px] font-bold uppercase tracking-[0.1em] text-ink/40">
                  <th className="px-3 py-2">Model</th>
                  <th className="px-3 py-2">Enabled</th>
                  <th className="px-3 py-2">Test</th>
                  <th className="px-3 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {p.models.map((m) => (
                  <tr key={m.id} className="border-t border-ink/[0.04]">
                    <td className="px-3 py-2">
                      <div className="font-semibold text-ink">{m.name}</div>
                      <div className="text-[10px] text-ink/40">{m.id}</div>
                    </td>
                    <td className="px-3 py-2">
                      <button
                        onClick={() => void toggleModel(p.provider, m.id, !m.enabled)}
                        disabled={busy !== null}
                        aria-label={m.enabled ? "Disable model" : "Enable model"}
                        className={`relative h-5 w-9 rounded-full transition disabled:opacity-40 ${m.enabled ? "bg-emerald-500" : "bg-ink/15"}`}
                      >
                        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${m.enabled ? "left-[18px]" : "left-0.5"}`} />
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      {m.tested_ok === null ? (
                        <span className="text-ink/30">never</span>
                      ) : m.tested_ok ? (
                        <span className="font-bold text-emerald-600">pass</span>
                      ) : (
                        <span className="font-bold text-coral">fail</span>
                      )}
                      {testResults[m.id] && (
                        <span className={`ml-2 font-bold ${testResults[m.id].ok ? "text-emerald-600" : "text-coral"}`}>
                          {testResults[m.id].ok ? "pass" : "fail"}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button onClick={() => void testModel(p.provider, m.id)} disabled={busy !== null} className="mr-2 text-[11px] font-semibold text-deep-violet hover:underline disabled:opacity-40">
                        Test
                      </button>
                      {m.custom && (
                        <button onClick={() => void deleteModel(p.provider, m.id)} disabled={busy !== null} className="text-[11px] font-semibold text-coral hover:underline disabled:opacity-40">
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-3">
            {showAdd === p.provider ? (
              <div className="rounded-xl border border-deep-violet/20 bg-deep-violet/[0.03] p-3">
                <div className="grid gap-2 sm:grid-cols-4">
                  <input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} placeholder="model id (e.g. my-model)" className="input-field" />
                  <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Display name" className="input-field" />
                  <input value={form.api_model} onChange={(e) => setForm({ ...form, api_model: e.target.value })} placeholder="Provider model name" className="input-field" />
                  <div className="flex gap-2">
                    <button onClick={() => void addModel(p.provider)} disabled={busy !== null || !form.id.trim() || !form.name.trim() || !form.api_model.trim()} className="flex-1 rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white disabled:opacity-40">
                      Add
                    </button>
                    <button onClick={() => setShowAdd(null)} className="rounded-lg border border-ink/10 px-3 py-1.5 text-[11px] font-bold text-ink/50">
                      Cancel
                    </button>
                  </div>
                </div>
                {(remote[p.provider] ?? []).length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {(remote[p.provider] ?? []).map((r) => (
                      <button
                        key={r.id}
                        type="button"
                        title="Click to prefill from this remote model"
                        onClick={() => setForm({ ...form, id: r.id.replace(/[^a-z0-9-]/gi, "-").toLowerCase(), name: r.name, api_model: r.id })}
                        className="rounded-full bg-white px-2 py-0.5 text-[10px] font-medium text-ink/60 ring-1 ring-ink/10 hover:ring-deep-violet/40"
                      >
                        {r.name || r.id}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <button onClick={() => { setShowAdd(p.provider); if (!(remote[p.provider] ?? []).length) void fetchRemote(p.provider); }} disabled={busy !== null} className="text-[12px] font-semibold text-deep-violet hover:underline disabled:opacity-40">
                + Add custom model
              </button>
            )}
          </div>
        </section>
      ))}
    </div>
  );
}
