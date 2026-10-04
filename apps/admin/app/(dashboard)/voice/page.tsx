"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

interface VoiceEngine {
  id: string;
  label: string;
  provider: string;
  tier: string;
  api_url: string | null;
  api_model: string | null;
  reference_id: string | null;
  language_references: Record<string, string> | null;
  languages: string;
  enabled: boolean;
  has_key: boolean;
}

interface FishVoice {
  id: string;
  title: string;
  languages: string[];
  tags: string[];
  likes: number | null;
  uses: number | null;
}

interface TestResult {
  ok: boolean;
  latency_ms: number;
  detail: string;
}

// Providers the admin can wire today. The built-in Edge voices need no key
// (they ship seeded); Fish Audio is the first keyed TTS engine.
const PROVIDERS = [
  {
    id: "fish",
    label: "Fish Audio",
    apiUrl: "https://api.fish.audio/v1/tts",
    models: ["s2.1-pro-free", "s2.1-pro", "s2-pro", "s1", "drama-3-preview"],
    modelHint: 'Sent as the "model" header — s2.1-pro-free is the free tier.',
  },
];

const TIER_DESC: Record<string, string> = {
  simple: "Fallback tier — the free built-in neural voices.",
  advanced: "Premium tier — tenants here expect the best voices.",
};

// Languages a voice pin can target. Empty key = the default multilingual
// voice; a per-language pin overrides it for that language only.
const LANGS: [string, string][] = [
  ["", "Default (all languages)"],
  ["en", "English"],
  ["ar", "Arabic"],
  ["ur", "Urdu"],
  ["ps", "Pashto"],
  ["hi", "Hindi"],
  ["bn", "Bengali"],
];
const langLabel = (code: string) => LANGS.find(([k]) => k === code)?.[1] ?? code;

export default function AdminVoicePage() {
  const [engines, setEngines] = useState<VoiceEngine[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, TestResult>>({});

  // Add-engine flow.
  const [adding, setAdding] = useState(false);
  const [fProvider, setFProvider] = useState("");
  const [fLabel, setFLabel] = useState("");
  const [fModel, setFModel] = useState("");
  const [fRef, setFRef] = useState("");
  const [fLangPins, setFLangPins] = useState<Record<string, string>>({});
  const [fPinLang, setFPinLang] = useState("ur");
  const [fPinRef, setFPinRef] = useState("");
  const [fApiUrl, setFApiUrl] = useState("");
  const [fKey, setFKey] = useState("");
  const [fTier, setFTier] = useState("advanced");
  const [fLanguages, setFLanguages] = useState("*");
  const [formError, setFormError] = useState<string | null>(null);

  // Edit flow: same fields, keyed by engine id (key blank = keep stored one).
  const [editing, setEditing] = useState<string | null>(null);
  const [editKey, setEditKey] = useState("");
  const [editRef, setEditRef] = useState<string | null>(null);
  const [editRefValue, setEditRefValue] = useState("");

  // Fish voice library browser. `browse` names where a picked voice goes:
  // "add" = the add-form (default voice or fPinLang), an engine id = saved
  // straight to that engine (browseLang decides default vs per-language).
  const [browse, setBrowse] = useState<{ ctx: string; lang: string } | null>(null);
  const [browseLang, setBrowseLang] = useState("");
  const [voices, setVoices] = useState<FishVoice[]>([]);
  const [voicePage, setVoicePage] = useState(1);
  const [voiceHasMore, setVoiceHasMore] = useState(false);
  const [voiceFilter, setVoiceFilter] = useState("*");
  const [voiceSort, setVoiceSort] = useState("task_count");
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setEngines(await adminFetch<VoiceEngine[]>("/api/v1/admin/voice-engines"));
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

  const providerOf = (id: string) => PROVIDERS.find((p) => p.id === id);

  const resetForm = () => {
    setAdding(false);
    setFProvider("");
    setFLabel("");
    setFModel("");
    setFRef("");
    setFLangPins({});
    setFPinLang("ur");
    setFPinRef("");
    setFApiUrl("");
    setFKey("");
    setFTier("advanced");
    setFLanguages("*");
    setFormError(null);
    setBrowse(null);
    setVoices([]);
  };

  const buildBody = (key: string | undefined) => ({
    label: fLabel.trim(),
    provider: fProvider,
    tier: fTier,
    api_url: fApiUrl.trim() || undefined,
    api_model: fModel.trim() || undefined,
    reference_id: fRef.trim() || undefined,
    language_references: Object.keys(fLangPins).length ? fLangPins : undefined,
    languages: fLanguages.trim() || "*",
    ...(key !== undefined ? { api_key: key } : {}),
  });

  const createEngine = async () => {
    if (!fProvider || !fLabel.trim()) {
      setFormError("Pick a provider and name the engine.");
      return;
    }
    setBusy("engine:add");
    setFormError(null);
    try {
      await adminFetch("/api/v1/admin/voice-engines", {
        method: "POST",
        body: JSON.stringify(buildBody(fKey.trim() || undefined)),
      });
      resetForm();
      await load();
      flash("Voice engine saved — tenants on that tier will use it.");
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(null);
    }
  };

  const updateEngine = async (engine: VoiceEngine, key: string | undefined, overrides?: Partial<VoiceEngine>) => {
    setBusy(engine.id);
    try {
      await adminFetch(`/api/v1/admin/voice-engines/${engine.id}`, {
        method: "PUT",
        body: JSON.stringify({
          label: engine.label,
          provider: engine.provider,
          tier: engine.tier,
          api_url: engine.api_url ?? undefined,
          api_model: engine.api_model ?? undefined,
          reference_id: engine.reference_id ?? undefined,
          languages: engine.languages || "*",
          enabled: engine.enabled,
          ...overrides,
          ...(key !== undefined ? { api_key: key } : {}),
        }),
      });
      await load();
      return true;
    } catch (e) {
      flash(e instanceof Error ? e.message : "Save failed.");
      return false;
    } finally {
      setBusy(null);
    }
  };

  const toggleEnabled = async (engine: VoiceEngine, enabled: boolean) => {
    const ok = await updateEngine(engine, undefined, { enabled });
    if (ok) flash(`${engine.label} ${enabled ? "enabled" : "disabled"}.`);
  };

  const saveEditKey = async (engine: VoiceEngine) => {
    if (await updateEngine(engine, editKey.trim() ? editKey.trim() : "")) {
      setEditing(null);
      setEditKey("");
      flash(editKey.trim() ? "API key stored (encrypted)." : "API key cleared.");
    }
  };

  const saveEditRef = async (engine: VoiceEngine) => {
    if (await updateEngine(engine, undefined, { reference_id: editRefValue.trim() || null })) {
      setEditRef(null);
      setEditRefValue("");
      flash(editRefValue.trim() ? "Voice pinned — every note now uses that persona." : "Voice pin cleared.");
    }
  };

  const clearKey = async (engine: VoiceEngine) => {
    if (!confirm(`Remove the stored key for ${engine.label}? Voice for that tier falls back or goes dark.`)) return;
    if (await updateEngine(engine, "")) flash("API key cleared.");
  };

  const deleteEngine = async (engine: VoiceEngine) => {
    if (!confirm(`Delete voice engine "${engine.label}"? Tenants on its tier lose voice until another engine is enabled.`)) return;
    setBusy(engine.id);
    try {
      await adminFetch(`/api/v1/admin/voice-engines/${engine.id}`, { method: "DELETE" });
      await load();
      flash("Engine deleted.");
    } catch (e) {
      flash(e instanceof Error ? e.message : "Delete failed.");
    } finally {
      setBusy(null);
    }
  };

  const runTest = async (engine: VoiceEngine) => {
    setBusy(`${engine.id}:test`);
    try {
      const res = await adminFetch<TestResult>(`/api/v1/admin/voice-engines/${engine.id}/test`, {
        method: "POST",
      });
      setTests((prev) => ({ ...prev, [engine.id]: res }));
    } catch (e) {
      setTests((prev) => ({
        ...prev,
        [engine.id]: { ok: false, latency_ms: 0, detail: e instanceof Error ? e.message : "Test failed." },
      }));
    } finally {
      setBusy(null);
    }
  };

  // ── Fish voice library ────────────────────────────────────────────────
  // fish.audio's list API ignores text search (their models carry a
  // languages field instead) — the UI filters by language client-side.

  const loadVoices = async (page: number, replace: boolean, sort = voiceSort) => {
    setVoiceLoading(true);
    setVoiceError(null);
    try {
      const res = await adminFetch<{ items: FishVoice[]; has_more: boolean }>(
        `/api/v1/admin/voice-engines/fish-voices?sort_by=${sort}&page=${page}`,
      );
      setVoices((prev) => (replace ? res.items : [...prev, ...res.items]));
      setVoicePage(page);
      setVoiceHasMore(res.has_more);
    } catch (e) {
      setVoiceError(e instanceof Error ? e.message : "Could not load voices.");
    } finally {
      setVoiceLoading(false);
    }
  };

  const openBrowse = (ctx: string, lang = "") => {
    setBrowseLang(lang);
    setVoiceFilter(lang || "*");
    setBrowse({ ctx, lang });
    void loadVoices(1, true);
  };

  const useVoice = async (voice: FishVoice) => {
    if (!browse) return;
    if (browse.ctx === "add") {
      if (browseLang) {
        setFLangPins((prev) => ({ ...prev, [browseLang]: voice.id }));
        flash(`Will pin "${voice.title}" for ${langLabel(browseLang)} on save.`);
      } else {
        setFRef(voice.id);
        flash(`Will use "${voice.title}" as the default voice on save.`);
      }
      return;
    }
    const engine = engines.find((e) => e.id === browse.ctx);
    if (!engine) return;
    const ok = await updateEngine(
      engine,
      undefined,
      browseLang
        ? {
            language_references: {
              ...(engine.language_references ?? {}),
              [browseLang]: voice.id,
            },
          }
        : { reference_id: voice.id },
    );
    if (ok) {
      flash(
        browseLang
          ? `"${voice.title}" pinned for ${langLabel(browseLang)}.`
          : `"${voice.title}" is now the default voice.`,
      );
    }
  };

  const removeLangPin = async (engine: VoiceEngine, lang: string) => {
    const rest = { ...(engine.language_references ?? {}) };
    delete rest[lang];
    const ok = await updateEngine(engine, undefined, {
      language_references: Object.keys(rest).length ? rest : null,
    });
    if (ok) flash(`${langLabel(lang)} pin removed — that language falls back to the default voice.`);
  };

  const filteredVoices =
    voiceFilter === "*" ? voices : voices.filter((v) => v.languages.includes(voiceFilter));

  const renderCatalog = () => (
    <div className="mt-3 rounded-xl border border-deep-violet/20 bg-white/70 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[11px] font-bold text-ink">Fish voice library</p>
        <select
          value={browseLang}
          onChange={(e) => {
            setBrowseLang(e.target.value);
            setVoiceFilter(e.target.value || "*");
          }}
          className="input-field w-40 py-1 text-[11px]"
          aria-label="Assign voice to"
        >
          {LANGS.map(([k, label]) => (
            <option key={k || "default"} value={k}>{label}</option>
          ))}
        </select>
        <select
          value={voiceFilter}
          onChange={(e) => setVoiceFilter(e.target.value)}
          className="input-field w-32 py-1 text-[11px]"
          aria-label="Filter by language"
        >
          <option value="*">All languages</option>
          {["en", "ar", "ur", "ps", "hi", "bn", "es", "ru", "pt", "ja", "fr"].map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <select
          value={voiceSort}
          onChange={(e) => {
            setVoiceSort(e.target.value);
            void loadVoices(1, true, e.target.value);
          }}
          className="input-field w-36 py-1 text-[11px]"
          aria-label="Sort voices"
        >
          <option value="task_count">Most used</option>
          <option value="score">Top scored</option>
          <option value="created_at">Newest</option>
        </select>
        <button
          onClick={() => void loadVoices(1, true)}
          disabled={voiceLoading}
          className="ml-auto rounded-lg px-2 py-1 text-[11px] font-semibold text-deep-violet hover:underline disabled:opacity-40"
        >
          {voiceLoading ? "Loading…" : "Refresh"}
        </button>
      </div>
      {voiceError && <p className="mt-2 text-[11px] text-coral">{voiceError}</p>}
      <ul className="mt-2 max-h-64 space-y-1.5 overflow-y-auto pr-1">
        {filteredVoices.map((v) => (
          <li key={v.id} className="flex items-center gap-2 rounded-lg bg-white px-2.5 py-1.5">
            <div className="min-w-0 flex-1">
              <p className="truncate text-[12px] font-semibold text-ink">{v.title}</p>
              <p className="truncate text-[10px] text-ink/45">
                {(v.languages.length ? v.languages.join(", ") : "unspecified")}
                {v.tags.length ? ` · ${v.tags.join(", ")}` : ""}
                {v.uses ? ` · ${v.uses.toLocaleString()} uses` : ""}
              </p>
            </div>
            <button
              onClick={() => void useVoice(v)}
              className="btn-primary shrink-0 !px-2.5 !py-1 text-[10px]"
            >
              Use
            </button>
          </li>
        ))}
        {filteredVoices.length === 0 && !voiceLoading && (
          <li className="py-2 text-center text-[11px] text-ink/45">
            {voiceFilter === "*"
              ? "No voices loaded yet."
              : `No ${voiceFilter} voices in this page — try the other sort or "All languages".`}
          </li>
        )}
      </ul>
      {voiceHasMore && (
        <button
          onClick={() => void loadVoices(voicePage + 1, false)}
          disabled={voiceLoading}
          className="mt-2 w-full rounded-lg border border-ink/[0.08] py-1.5 text-[11px] font-semibold text-ink/55 hover:border-deep-violet/30 disabled:opacity-40"
        >
          {voiceLoading ? "Loading…" : "Load more"}
        </button>
      )}
      <p className="mt-2 text-[10px] text-ink/40">
        “Use” saves it as {browseLang ? `the ${langLabel(browseLang)} voice` : "the default voice"}.
        Urdu/Pashto voices are rare in the top ranks — use the manual ID field for those.
      </p>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Voice models</h1>
          <p className="mt-0.5 max-w-xl text-[12px] text-ink/50">
            Which engine speaks WhatsApp voice notes per tenant tier. Tenants only ever
            pick Off / Simple / Advanced — the engine behind each tier is decided here.
            Keys are stored encrypted and never displayed back.
          </p>
        </div>
        {!adding && (
          <button onClick={() => setAdding(true)} className="btn-primary !px-3 !py-1.5">
            + Add voice model
          </button>
        )}
      </div>

      {notice && (
        <div role="status" className="rounded-xl border border-deep-violet/20 bg-white px-4 py-2.5 text-[12px] font-medium text-ink/70">
          {notice}
        </div>
      )}

      {adding && (
        <div className="space-y-3 rounded-[6px] border-2 border-white bg-white/80 p-5">
          <p className="text-[14px] font-bold text-ink">Add a voice model</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">1 · Provider</label>
              <select
                value={fProvider}
                onChange={(e) => {
                  setFProvider(e.target.value);
                  setFApiUrl(providerOf(e.target.value)?.apiUrl ?? "");
                  setFModel("");
                }}
                className="input-field"
              >
                <option value="">Select provider…</option>
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>{p.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">2 · Serves tier</label>
              <select value={fTier} onChange={(e) => setFTier(e.target.value)} className="input-field">
                <option value="advanced">Advanced</option>
                <option value="simple">Simple</option>
              </select>
              <p className="mt-0.5 text-[10px] text-ink/40">{TIER_DESC[fTier]}</p>
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">3 · Label</label>
              <input
                value={fLabel}
                onChange={(e) => setFLabel(e.target.value)}
                placeholder="Fish Audio (advanced)"
                className="input-field"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">4 · Model name</label>
              <input
                value={fModel}
                onChange={(e) => setFModel(e.target.value)}
                list="fish-models"
                placeholder={providerOf(fProvider)?.models[0] ?? "model-id"}
                className="input-field font-mono text-[11px]"
              />
              <datalist id="fish-models">
                {(providerOf(fProvider)?.models ?? []).map((m) => (
                  <option key={m} value={m} />
                ))}
              </datalist>
              {fProvider && (
                <p className="mt-0.5 text-[10px] text-ink/40">{providerOf(fProvider)?.modelHint}</p>
              )}
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">5 · Voice</label>
              <div className="flex gap-2">
                <input
                  value={fRef}
                  onChange={(e) => setFRef(e.target.value)}
                  placeholder="reference_id — pins the voice persona"
                  className="input-field font-mono text-[11px]"
                />
                <button
                  type="button"
                  onClick={() => openBrowse("add", "")}
                  className="btn-secondary shrink-0 !px-2.5 !py-1.5 text-[11px]"
                >
                  Browse
                </button>
              </div>
              <p className="mt-0.5 text-[10px] text-ink/40">
                The default persona for every language. Pick one at fish.audio/voice or browse the
                library — without a pin the persona changes every note.
              </p>
              <div className="mt-2 rounded-xl border border-dashed border-ink/[0.12] p-2.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-ink/45">
                  Language voices (optional)
                </p>
                <div className="mt-1.5 flex gap-2">
                  <select value={fPinLang} onChange={(e) => setFPinLang(e.target.value)} className="input-field w-28 shrink-0 text-[11px]">
                    {LANGS.filter(([k]) => k).map(([k, label]) => (
                      <option key={k} value={k}>{label}</option>
                    ))}
                  </select>
                  <input
                    value={fPinRef}
                    onChange={(e) => setFPinRef(e.target.value)}
                    placeholder="voice id for this language"
                    className="input-field flex-1 font-mono text-[11px]"
                  />
                  <button
                    type="button"
                    onClick={() => openBrowse("add", fPinLang)}
                    className="btn-secondary shrink-0 !px-2.5 !py-1.5 text-[11px]"
                  >
                    Browse
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (!fPinRef.trim()) return;
                      setFLangPins((prev) => ({ ...prev, [fPinLang]: fPinRef.trim() }));
                      setFPinRef("");
                    }}
                    disabled={!fPinRef.trim()}
                    className="btn-secondary shrink-0 !px-2.5 !py-1.5 text-[11px] disabled:opacity-40"
                  >
                    Add
                  </button>
                </div>
                {Object.keys(fLangPins).length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {Object.entries(fLangPins).map(([lang, ref]) => (
                      <span key={lang} className="flex items-center gap-1 rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-semibold text-deep-violet">
                        {langLabel(lang)}: {ref.slice(0, 8)}…
                        <button
                          type="button"
                          onClick={() => setFLangPins((prev) => {
                            const rest = { ...prev };
                            delete rest[lang];
                            return rest;
                          })}
                          className="font-bold opacity-50 hover:opacity-100"
                          aria-label={`Remove ${langLabel(lang)} pin`}
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <p className="mt-1.5 text-[10px] text-ink/40">
                  A customer speaking a pinned language hears that voice; everyone else hears the
                  default. No pins = one voice for all.
                </p>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">6 · API endpoint</label>
              <input
                value={fApiUrl}
                onChange={(e) => setFApiUrl(e.target.value)}
                placeholder="https://api.fish.audio/v1/tts"
                className="input-field font-mono text-[11px]"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">7 · API key</label>
              <input
                type="password"
                value={fKey}
                onChange={(e) => setFKey(e.target.value)}
                placeholder="sk-… — typed here, stored encrypted on Save"
                autoComplete="off"
                className="input-field"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-semibold text-ink/50">8 · Languages</label>
              <input
                value={fLanguages}
                onChange={(e) => setFLanguages(e.target.value)}
                placeholder="* or ar,en,ur"
                className="input-field font-mono text-[11px]"
              />
              <p className="mt-0.5 text-[10px] text-ink/40">* = all languages.</p>
            </div>
          </div>
          {formError && <p className="text-[11px] text-coral">{formError}</p>}
          {browse?.ctx === "add" && renderCatalog()}
          <div className="flex gap-2">
            <button onClick={() => void createEngine()} disabled={busy !== null} className="btn-primary !px-4 !py-2 disabled:opacity-50">
              {busy === "engine:add" ? "Saving…" : "Save engine"}
            </button>
            <button onClick={resetForm} className="btn-secondary !px-4 !py-2">
              Cancel
            </button>
          </div>
        </div>
      )}

      {error ? (
        <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[13px] font-semibold text-ink/60">{error}</p>
        </div>
      ) : loading && engines.length === 0 ? (
        <div className="space-y-3" aria-hidden>
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-[6px] border-2 border-white bg-white/60" />
          ))}
        </div>
      ) : engines.length === 0 ? (
        <div className="rounded-[6px] border-2 border-white bg-white/80 p-10 text-center">
          <p className="text-[14px] font-semibold text-ink/70">No voice engines yet</p>
          <p className="mt-1 text-[12px] text-ink/45">
            Tenants get no voice notes until you enable one engine per tier.
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {engines.map((engine) => {
            const isBusy = busy === engine.id || busy === `${engine.id}:test`;
            const test = tests[engine.id];
            const isEdge = engine.provider === "edge";
            return (
              <li
                key={engine.id}
                className={`rounded-[6px] border-2 bg-white/80 p-4 backdrop-blur-sm transition ${
                  engine.enabled ? "border-white hover:shadow-lg hover:shadow-deep-violet/[0.08]" : "border-ink/[0.06] opacity-75"
                }`}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[6px] bg-gradient-to-br from-deep-violet to-magenta text-[16px] text-white shadow-md" aria-hidden>
                    {isEdge ? "🎙" : "🐟"}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-center gap-1.5 text-[14px] font-bold text-ink">
                      {engine.label}
                      <span className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-deep-violet">
                        {engine.tier}
                      </span>
                      <span className="rounded bg-ink/[0.05] px-1.5 py-0.5 text-[10px] font-semibold capitalize text-ink/50">
                        {engine.provider}
                      </span>
                      {!engine.enabled && (
                        <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase text-ink/45">
                          off
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 truncate font-mono text-[11px] text-ink/45">
                      {engine.api_model || "default voice"}
                      {engine.reference_id ? ` · voice ${engine.reference_id.slice(0, 8)}…` : " · default persona"}
                      {engine.api_url ? ` · ${engine.api_url}` : ""}
                    </p>
                    {engine.language_references && Object.keys(engine.language_references).length > 0 && (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {Object.entries(engine.language_references).map(([lang, ref]) => (
                          <span key={lang} className="flex items-center gap-1 rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-semibold text-deep-violet">
                            {langLabel(lang)}: {ref.slice(0, 6)}…
                            <button
                              onClick={() => void removeLangPin(engine, lang)}
                              disabled={isBusy}
                              className="font-bold opacity-50 hover:opacity-100 disabled:opacity-30"
                              aria-label={`Remove ${langLabel(lang)} voice pin`}
                            >
                              ✕
                            </button>
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <select
                    value={engine.enabled ? "enabled" : "disabled"}
                    disabled={isBusy}
                    onChange={(e) => void toggleEnabled(engine, e.target.value === "enabled")}
                    aria-label={`${engine.label} status`}
                    className={`ml-auto shrink-0 cursor-pointer rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[11px] font-bold outline-none transition focus:border-deep-violet/30 disabled:opacity-50 ${
                      engine.enabled ? "text-emerald-600" : "text-ink/40"
                    }`}
                  >
                    <option value="enabled">Enabled</option>
                    <option value="disabled">Disabled</option>
                  </select>
                </div>

                <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-ink/45">
                  <span className="rounded bg-ink/[0.04] px-1.5 py-0.5">
                    {engine.languages === "*" ? "all languages" : engine.languages}
                  </span>
                  <span className={`rounded px-1.5 py-0.5 font-semibold ${engine.has_key ? "bg-emerald-50 text-emerald-700" : "bg-ink/[0.04] text-ink/40"}`}>
                    {isEdge ? "no key needed" : engine.has_key ? "key stored" : "no key"}
                  </span>
                </div>

                {editing === engine.id ? (
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-ink/[0.05] pt-3">
                    <input
                      type="password"
                      value={editKey}
                      onChange={(e) => setEditKey(e.target.value)}
                      placeholder="Paste new API key (empty = clear)…"
                      autoComplete="off"
                      className="input-field min-w-[220px] flex-1"
                    />
                    <button
                      onClick={() => void saveEditKey(engine)}
                      disabled={isBusy}
                      className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => {
                        setEditing(null);
                        setEditKey("");
                      }}
                      className="btn-secondary !px-3 !py-1.5"
                    >
                      Cancel
                    </button>
                  </div>
                ) : editRef === engine.id ? (
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-ink/[0.05] pt-3">
                    <input
                      value={editRefValue}
                      onChange={(e) => setEditRefValue(e.target.value)}
                      placeholder="fish.audio voice ID (empty = clear pin)…"
                      className="input-field min-w-[220px] flex-1 font-mono text-[11px]"
                    />
                    <button
                      onClick={() => void saveEditRef(engine)}
                      disabled={isBusy}
                      className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => {
                        setEditRef(null);
                        setEditRefValue("");
                      }}
                      className="btn-secondary !px-3 !py-1.5"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <div className="mt-3 flex flex-wrap gap-2 border-t border-ink/[0.05] pt-3">
                    {!isEdge && (
                      <>
                        <button
                          onClick={() => {
                            setEditing(engine.id);
                            setEditKey("");
                          }}
                          disabled={isBusy}
                          className="btn-secondary !px-3 !py-1.5 disabled:opacity-50"
                        >
                          {engine.has_key ? "Replace key" : "Add key"}
                        </button>
                        {engine.has_key && (
                          <button
                            onClick={() => void clearKey(engine)}
                            disabled={isBusy}
                            className="rounded-xl px-3 py-1.5 text-[11px] font-semibold text-ink/40 transition hover:text-coral disabled:opacity-50"
                          >
                            Clear key
                          </button>
                        )}
                        <button
                          onClick={() => {
                            setEditRef(engine.id);
                            setEditRefValue(engine.reference_id ?? "");
                          }}
                          disabled={isBusy}
                          className="btn-secondary !px-3 !py-1.5 disabled:opacity-50"
                        >
                          {engine.reference_id ? "Change voice" : "Pin voice"}
                        </button>
                        <button
                          onClick={() =>
                            browse?.ctx === engine.id ? setBrowse(null) : openBrowse(engine.id, "")
                          }
                          disabled={isBusy}
                          className="btn-secondary !px-3 !py-1.5 disabled:opacity-50"
                        >
                          {browse?.ctx === engine.id ? "Close library" : "Browse voices"}
                        </button>
                      </>
                    )}
                    <button
                      onClick={() => void runTest(engine)}
                      disabled={isBusy}
                      className="ml-auto rounded-xl bg-emerald-500 px-3 py-1.5 text-[11px] font-bold text-white shadow-sm transition hover:bg-emerald-600 disabled:opacity-50"
                    >
                      {busy === `${engine.id}:test` ? "Speaking…" : "Test"}
                    </button>
                    <button
                      onClick={() => void deleteEngine(engine)}
                      disabled={isBusy}
                      aria-label={`Delete ${engine.label}`}
                      className="rounded-xl px-2.5 py-1.5 text-[11px] font-bold text-ink/30 transition hover:text-coral disabled:opacity-50"
                    >
                      ✕
                    </button>
                  </div>
                )}

                {test && (
                  <p className={`mt-2 text-[11px] font-medium ${test.ok ? "text-emerald-600" : "text-coral"}`}>
                    {test.ok ? `✓ ${test.detail} (${test.latency_ms}ms)` : `✗ ${test.detail}`}
                  </p>
                )}

                {browse?.ctx === engine.id && renderCatalog()}
              </li>
            );
          })}
        </ul>
      )}

      <div className="rounded-xl border border-dashed border-ink/[0.12] bg-white/50 p-4 text-[11px] leading-relaxed text-ink/45">
        <p className="font-semibold text-ink/60">How tiers work</p>
        <p className="mt-1">
          A tenant picks a tier on their WhatsApp channel — Off, Simple, or Advanced. When a customer
          seems confused, the AI answers with a short voice note in the customer&apos;s language, spoken
          by the engine you enable for that tier. A keyed engine always wins over the built-in Edge
          voices for the same tier; if no engine can speak, the customer gets the text reply instead.
        </p>
      </div>
    </div>
  );
}
