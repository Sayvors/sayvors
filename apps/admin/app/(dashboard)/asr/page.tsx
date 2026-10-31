"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchASR,
  saveASR,
  testASR,
  type ASRProvider,
  type ASRTestResult,
} from "@/lib/asr-api";

const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";
const INPUT =
  "w-full rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] text-ink outline-none transition focus:border-deep-violet";

interface Draft {
  model: string;
  baseUrl: string;
  languages: string;
  enabled: boolean;
  active: boolean;
  key: string;
}

function draftOf(p: ASRProvider): Draft {
  return {
    model: p.model ?? p.default_model ?? "",
    baseUrl: p.base_url ?? "",
    languages: p.languages || "*",
    enabled: p.enabled,
    active: p.active,
    key: "",
  };
}

export default function AdminAsrPage() {
  const [providers, setProviders] = useState<ASRProvider[]>([]);
  const [activeProvider, setActiveProvider] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [tests, setTests] = useState<Record<string, ASRTestResult>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const apply = useCallback((list: ASRProvider[], active: string | null) => {
    setProviders(list);
    setActiveProvider(active);
    setDrafts(Object.fromEntries(list.map((p) => [p.provider, draftOf(p)])));
  }, []);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetchASR()
      .then((data) => apply(data.providers, data.active_provider))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load ASR providers."))
      .finally(() => setLoading(false));
  }, [apply]);

  useEffect(() => { load(); }, [load]);

  const setDraft = useCallback((provider: string, patch: Partial<Draft>) => {
    setDrafts((prev) => ({ ...prev, [provider]: { ...prev[provider], ...patch } }));
  }, []);

  const save = useCallback(async (p: ASRProvider) => {
    const d = drafts[p.provider];
    if (!d) return;
    setBusy(p.provider);
    setError(null);
    setNotice(null);
    try {
      await saveASR(p.provider, {
        model: p.needs_key ? d.model || null : null,
        base_url: p.needs_key ? d.baseUrl || null : null,
        languages: d.languages || "*",
        enabled: d.enabled,
        active: d.active,
        // Only send the key when the admin typed one: omitted keeps the
        // stored key, and an empty string would clear it.
        ...(d.key ? { api_key: d.key } : {}),
      });
      setNotice(`${p.label} saved.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  }, [drafts, load]);

  const activate = useCallback(async (p: ASRProvider, active: boolean) => {
    const d = drafts[p.provider];
    if (!d) return;
    setBusy(p.provider);
    setError(null);
    setNotice(null);
    try {
      await saveASR(p.provider, {
        model: p.needs_key ? d.model || null : null,
        base_url: p.needs_key ? d.baseUrl || null : null,
        languages: d.languages || "*",
        enabled: active ? true : d.enabled,
        active,
        // Activation never re-sends the key; the stored one is reused, so a
        // mistyped field cannot silently wipe a working key.
        ...(d.key ? { api_key: d.key } : {}),
      });
      setNotice(active ? `${p.label} is now the active ASR engine.` : `${p.label} deactivated.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change the active engine.");
    } finally {
      setBusy(null);
    }
  }, [drafts, load]);

  const runTest = useCallback(async (p: ASRProvider) => {
    setBusy(p.provider);
    setTests((prev) => {
      const next = { ...prev };
      delete next[p.provider];
      return next;
    });
    try {
      const result = await testASR(p.provider);
      setTests((prev) => ({ ...prev, [p.provider]: result }));
    } catch (e) {
      setTests((prev) => ({
        ...prev,
        [p.provider]: {
          ok: false,
          latency_ms: 0,
          detail: e instanceof Error ? e.message : "Test failed.",
        },
      }));
    } finally {
      setBusy(null);
    }
  }, []);

  const order = useMemo(
    () => [...providers].sort((a, b) => Number(b.needs_key) - Number(a.needs_key)),
    [providers],
  );

  return (
    <div className="space-y-4">
      <div className="admin-rise flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-ink/40">Sayvors · Admin</p>
          <h1 className="mt-1 text-[22px] font-bold tracking-tight text-ink">Speech-to-text</h1>
          <p className="mt-1.5 max-w-[720px] text-[14px] font-medium leading-relaxed text-ink sm:text-[15px]">
            Voice notes are transcribed by the <b className="font-bold text-deep-violet">active engine</b>.
            Keys are encrypted at rest and never shown again. With no active engine, transcription
            falls back to the local faster-whisper model.
          </p>
        </div>
        <button
          onClick={load}
          className={`shrink-0 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet ${FOCUS_RING}`}
        >
          Refresh
        </button>
      </div>

      <div className="rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3.5 py-3 text-[12px] text-ink/70">
        Active engine:{" "}
        <b className="font-bold text-ink">
          {activeProvider
            ? providers.find((p) => p.provider === activeProvider)?.label ?? activeProvider
            : "Local faster-whisper (fallback)"}
        </b>
      </div>

      {error ? (
        <div role="alert" className="rounded-[2px] border border-red-200 bg-red-50 px-3 py-2.5 text-[12px] text-red-700">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="rounded-[2px] border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-[12px] text-emerald-800">
          {notice}
        </div>
      ) : null}

      {loading ? (
        <div className="grid gap-3 lg:grid-cols-2" aria-hidden aria-label="Loading ASR providers">
          {[1, 2].map((i) => <div key={i} className="h-52 animate-pulse rounded-[2px] bg-ink/[0.04]" />)}
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {order.map((p) => {
            const d = drafts[p.provider] ?? draftOf(p);
            const test = tests[p.provider];
            const selected = activeProvider === p.provider;
            return (
              <section
                key={p.provider}
                aria-labelledby={`asr-${p.provider}`}
                className={`panel p-4 sm:p-5 ${selected ? "ring-1 ring-deep-violet/40" : ""}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 id={`asr-${p.provider}`} className="text-[14px] font-bold text-ink">
                      {p.label}
                    </h2>
                    <p className="mt-1 text-[11px] leading-relaxed text-ink/50">{p.note}</p>
                  </div>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                      selected
                        ? "bg-emerald-500 text-white"
                        : p.has_key || !p.needs_key
                          ? "bg-ink/[0.06] text-ink/50"
                          : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {selected ? "Active" : p.has_key || !p.needs_key ? "Available" : "No key"}
                  </span>
                </div>

                {p.needs_key ? (
                  <div className="mt-4 space-y-3">
                    <label className="block">
                      <span className="block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">
                        API key {p.has_key ? "· stored" : ""}
                      </span>
                      <input
                        type="password"
                        autoComplete="off"
                        value={d.key}
                        onChange={(e) => setDraft(p.provider, { key: e.target.value })}
                        placeholder={p.has_key ? "•••••••• (leave blank to keep)" : "Paste the provider key"}
                        className={`mt-1 ${INPUT} ${FOCUS_RING}`}
                      />
                      <span className="mt-1 block text-[10.5px] text-ink/40">
                        Only the speech-to-text permission is required.
                      </span>
                    </label>

                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="block">
                        <span className="block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">Model</span>
                        {p.models.length > 0 ? (
                          <select
                            value={d.model}
                            onChange={(e) => setDraft(p.provider, { model: e.target.value })}
                            className={`mt-1 ${INPUT} ${FOCUS_RING}`}
                          >
                            {p.models.map((m) => <option key={m} value={m}>{m}</option>)}
                          </select>
                        ) : (
                          <input
                            value={d.model}
                            onChange={(e) => setDraft(p.provider, { model: e.target.value })}
                            className={`mt-1 ${INPUT} ${FOCUS_RING}`}
                          />
                        )}
                      </label>
                      <label className="block">
                        <span className="block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">Languages</span>
                        <input
                          value={d.languages}
                          onChange={(e) => setDraft(p.provider, { languages: e.target.value })}
                          placeholder="* or ar,en,ur"
                          className={`mt-1 ${INPUT} ${FOCUS_RING}`}
                        />
                        <span className="mt-1 block text-[10.5px] text-ink/40">
                          A note outside this list uses the local fallback.
                        </span>
                      </label>
                    </div>

                    <label className="block">
                      <span className="block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">
                        Base URL <span className="normal-case tracking-normal text-ink/30">(optional)</span>
                      </span>
                      <input
                        value={d.baseUrl}
                        onChange={(e) => setDraft(p.provider, { baseUrl: e.target.value })}
                        placeholder="https://api.elevenlabs.io"
                        className={`mt-1 ${INPUT} ${FOCUS_RING}`}
                      />
                    </label>
                  </div>
                ) : (
                  <p className="mt-4 rounded-[2px] bg-ink/[0.03] px-3 py-2.5 text-[11.5px] leading-relaxed text-ink/60">
                    Runs in this process. No key, no network, no per-minute cost — slower and less
                    accurate than a hosted engine, which is why it is the fallback.
                  </p>
                )}

                {test ? (
                  <div
                    role="status"
                    className={`mt-3 rounded-[2px] border px-3 py-2 text-[11px] leading-relaxed ${
                      test.ok
                        ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                        : "border-red-200 bg-red-50 text-red-700"
                    }`}
                  >
                    {test.ok ? "Test passed" : "Test failed"} · {test.latency_ms} ms — {test.detail}
                  </div>
                ) : null}

                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {p.needs_key && (
                    <>
                      <button
                        onClick={() => save(p)}
                        disabled={busy === p.provider}
                        className={`rounded-[2px] bg-deep-violet px-3.5 py-2 text-[11px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50 ${FOCUS_RING}`}
                      >
                        {busy === p.provider ? "Saving…" : "Save"}
                      </button>
                      <button
                        onClick={() => runTest(p)}
                        disabled={busy === p.provider || !p.has_key}
                        className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-2 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet disabled:opacity-40 ${FOCUS_RING}`}
                      >
                        Test
                      </button>
                    </>
                  )}
                  {selected ? (
                    <button
                      onClick={() => activate(p, false)}
                      disabled={busy === p.provider}
                      className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-2 text-[11px] font-semibold text-ink/60 transition hover:border-red-300 hover:text-red-600 disabled:opacity-40 ${FOCUS_RING}`}
                    >
                      Deactivate
                    </button>
                  ) : (
                    <button
                      onClick={() => activate(p, true)}
                      disabled={busy === p.provider || (p.needs_key && !p.has_key && !d.key)}
                      title={
                        p.needs_key && !p.has_key && !d.key
                          ? "Save a key first"
                          : undefined
                      }
                      className={`rounded-[2px] border border-deep-violet bg-[var(--ui-surface)] px-3 py-2 text-[11px] font-bold text-deep-violet transition hover:bg-deep-violet hover:text-white disabled:opacity-40 ${FOCUS_RING}`}
                    >
                      Use this engine
                    </button>
                  )}
                  {p.docs ? (
                    <a
                      href={p.docs}
                      target="_blank"
                      rel="noreferrer"
                      className={`ml-auto text-[11px] font-semibold text-ink/40 underline decoration-dotted transition hover:text-deep-violet ${FOCUS_RING}`}
                    >
                      API docs
                    </a>
                  ) : null}
                </div>
              </section>
            );
          })}
        </div>
      )}

      <p className="pb-2 text-center text-[11px] text-ink/25">
        One active engine at a time. A failed hosted call falls back to the local model, so a bad
        key degrades quality instead of losing the voice note.
      </p>
    </div>
  );
}
