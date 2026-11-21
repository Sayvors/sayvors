"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import LlmsPage from "../llms/page";

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

interface SavedModel {
  id: string;
  name: string;
  provider: string;
  api_model: string;
  enabled: boolean;
  custom?: boolean;
  supports_vision?: boolean | null;
}

interface AiConfig {
  banner_vision_model: string | null;
  banner_decision_model: string | null;
  updated_at: string | null;
}

interface ModelTestResult {
  model_id: string;
  ok: boolean;
  latency_ms: number;
  detail: string;
  reply: string;
}

export default function AiImageCheckPage() {
  const [models, setModels] = useState<SavedModel[]>([]);
  const [config, setConfig] = useState<AiConfig | null>(null);
  const [savedId, setSavedId] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busySave, setBusySave] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, ModelTestResult>>({});
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async (keepSelection = false) => {
    setLoading(true);
    try {
      const [modelList, cfg, providers] = await Promise.all([
        adminFetch<SavedModel[]>("/api/v1/admin/models"),
        adminFetch<AiConfig>("/api/v1/admin/config/ai"),
        adminFetch<Array<{ models?: Array<{ id: string; supports_vision?: boolean | null }> }>>(
          "/api/v1/admin/llm"
        ),
      ]);
      // Older API builds omit supports_vision from /admin/models; the provider
      // list carries it, so merge before filtering.
      const visionById = new Map<string, boolean | null>();
      for (const p of providers) {
        for (const m of p.models ?? []) {
          visionById.set(m.id, m.supports_vision ?? null);
        }
      }
      const visionModels = modelList
        .map((m) => ({
          ...m,
          supports_vision: m.supports_vision ?? visionById.get(m.id) ?? null,
        }))
        .filter((m) => m.enabled && m.supports_vision);
      setModels(visionModels);
      setConfig(cfg);
      const activeId = cfg.banner_vision_model ?? "";
      setSavedId(activeId);
      setSelectedId((prev) => {
        if (keepSelection && prev && visionModels.some((m) => m.id === prev)) {
          return prev;
        }
        return activeId;
      });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : "Could not load the model list." });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const savedModel = models.find((m) => m.id === savedId) ?? null;
  const selectedModel = models.find((m) => m.id === selectedId) ?? null;
  const savedUnavailable = Boolean(savedId) && !savedModel;
  const dirty = selectedId !== savedId;

  async function runTest(m: SavedModel) {
    setTestingId(m.id);
    try {
      const res = await adminFetch<ModelTestResult>(
        `/api/v1/admin/llm/${m.provider}/models/${encodeURIComponent(m.id)}/test`,
        { method: "POST" }
      );
      setTests((prev) => ({ ...prev, [m.id]: res }));
    } catch (e) {
      setTests((prev) => ({
        ...prev,
        [m.id]: {
          model_id: m.id, ok: false, latency_ms: 0,
          detail: e instanceof Error ? e.message : "Test failed.", reply: "",
        },
      }));
    } finally {
      setTestingId(null);
    }
  }

  async function save() {
    setBusySave(true);
    setMessage(null);
    try {
      const saved = await adminFetch<AiConfig>("/api/v1/admin/config/ai", {
        method: "PUT",
        body: JSON.stringify({
          banner_vision_model: selectedId,
        }),
      });
      setConfig(saved);
      setSavedId(saved.banner_vision_model ?? "");
      setMessage({
        ok: true,
        text: selectedId
          ? `Saved — tenants will use ${selectedModel?.name ?? selectedId} for the photo check.`
          : "Saved — the photo check now runs on rules only.",
      });
    } catch (e) {
      setMessage({ ok: false, text: e instanceof Error ? e.message : "Could not save the selection." });
    } finally {
      setBusySave(false);
    }
  }

  function scrollToModelList() {
    document.getElementById("llm-models")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  let saveHint = "The rule-based check is already in use.";
  if (savedUnavailable) {
    saveHint = "The saved model is unavailable — pick a replacement or switch to rules only.";
  } else if (dirty) {
    saveHint = "Unsaved change — press save to apply it.";
  } else if (selectedId) {
    saveHint = "This model is already in use.";
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">Intelligence · AI image check</p>
        <h1 className="mt-1 text-[26px] font-bold leading-none tracking-tight text-ink">Banner &amp; promotion photo check</h1>
        <p className="mt-2 max-w-[680px] text-[13px] font-medium leading-relaxed text-ink/60">
          Choose the model that looks at uploaded Promotion photos. Only enabled vision-capable models
          are listed. Tenants never see which model you pick.
        </p>
      </div>

      <section className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[16px] font-bold text-ink">Which model checks the photo?</h2>
            <p className="mt-0.5 text-[12px] text-ink/50">
              Pick one option, test it if you like, then save. Changes apply to the next upload.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={loading}
            className={`shrink-0 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wide text-ink/60 transition hover:border-[var(--ui-ink)] hover:text-ink disabled:opacity-50 ${FOCUS_RING}`}
          >
            {loading ? "Loading…" : "Refresh list"}
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-1 rounded-[2px] border border-[var(--ui-line)] bg-ink/[0.02] px-3 py-2 text-[12px]">
          <span className="flex min-w-0 items-center gap-1.5">
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${savedModel ? "bg-emerald-500" : savedId ? "bg-amber-500" : "bg-ink/25"}`} />
            <span className="shrink-0 text-ink/50">In use</span>
            <span className="truncate font-semibold text-ink">
              {savedModel?.name ?? (savedId ? "Unavailable model" : "Rule-based only")}
            </span>
            {savedId ? (
              <span className="hidden truncate font-mono text-[10px] text-ink/40 sm:inline">{savedId}</span>
            ) : null}
          </span>
          <span className="text-ink/45">
            Last updated {config?.updated_at ? new Date(config.updated_at).toLocaleString() : "—"}
          </span>
        </div>

        {savedUnavailable ? (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-[2px] border border-amber-300 bg-amber-50 px-3 py-2">
            <p className="text-[12px] font-medium text-amber-900">
              The saved model <span className="font-mono text-[11px]">{savedId}</span> is disabled, deleted, or
              no longer marked as vision-capable. Pick a replacement below, or switch to rules only.
            </p>
            <button
              type="button"
              onClick={() => setSelectedId("")}
              className={`shrink-0 rounded-[2px] border border-amber-400 bg-white px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-amber-900 transition hover:bg-amber-100 ${FOCUS_RING}`}
            >
              Switch to rules only
            </button>
          </div>
        ) : null}

        <div role="radiogroup" aria-label="Photo check model" className="mt-4 space-y-2">
          <div
            className={`flex items-start gap-3 rounded-[2px] border p-3 transition ${
              selectedId === ""
                ? "border-deep-violet bg-deep-violet/[0.04]"
                : "border-[var(--ui-line)] hover:border-[var(--ui-line-strong)]"
            }`}
          >
            <input
              id="vision-rule-based"
              type="radio"
              name="vision-model"
              checked={selectedId === ""}
              onChange={() => setSelectedId("")}
              className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer accent-deep-violet"
            />
            <label htmlFor="vision-rule-based" className="min-w-0 flex-1 cursor-pointer">
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] font-semibold text-ink">Rule-based check only</span>
                {!savedId ? (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[9px] font-bold uppercase text-emerald-700">
                    in use
                  </span>
                ) : null}
              </span>
              <span className="mt-0.5 block text-[11px] leading-relaxed text-ink/50">
                Checks format, size, shape, sharpness and exposure without calling a model — instant and free.
              </span>
            </label>
          </div>

          {loading ? (
            <p className="rounded-[2px] border border-dashed border-[var(--ui-line-strong)] p-4 text-center text-[12px] text-ink/40">
              Loading vision-capable models…
            </p>
          ) : models.length === 0 ? (
            <div className="rounded-[2px] border border-dashed border-[var(--ui-line-strong)] p-4">
              <p className="text-[12px] font-semibold text-ink">No vision-capable models are enabled yet.</p>
              <p className="mt-1 text-[11px] leading-relaxed text-ink/50">
                In the model list below, switch a model on and tick its <span className="font-semibold text-ink/70">vision</span> checkbox.
                It will appear here.
              </p>
              <button
                type="button"
                onClick={scrollToModelList}
                className={`mt-2 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wide text-ink/70 transition hover:border-[var(--ui-ink)] hover:text-ink ${FOCUS_RING}`}
              >
                Go to model list ↓
              </button>
            </div>
          ) : null}

          {models.map((m, index) => {
            const inputId = `vision-option-${index}`;
            const isSelected = selectedId === m.id;
            const isActive = savedId === m.id;
            const result = tests[m.id];
            const isTesting = testingId === m.id;
            return (
              <div
                key={m.id}
                className={`rounded-[2px] border transition ${
                  isSelected
                    ? "border-deep-violet bg-deep-violet/[0.04]"
                    : "border-[var(--ui-line)] hover:border-[var(--ui-line-strong)]"
                }`}
              >
                <div className="flex items-center gap-3 p-3">
                  <input
                    id={inputId}
                    type="radio"
                    name="vision-model"
                    checked={isSelected}
                    onChange={() => setSelectedId(m.id)}
                    className="h-4 w-4 shrink-0 cursor-pointer accent-deep-violet"
                  />
                  <label htmlFor={inputId} className="min-w-0 flex-1 cursor-pointer">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-[13px] font-semibold text-ink">{m.name}</span>
                      {isActive ? (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[9px] font-bold uppercase text-emerald-700">
                          in use
                        </span>
                      ) : null}
                      {m.custom ? (
                        <span className="rounded bg-deep-violet/10 px-1.5 py-px text-[9px] font-bold uppercase text-deep-violet">
                          custom
                        </span>
                      ) : null}
                    </span>
                    <span className="mt-0.5 block truncate font-mono text-[10px] text-ink/40">
                      {m.provider} · {m.api_model}
                    </span>
                  </label>
                  <button
                    type="button"
                    onClick={() => void runTest(m)}
                    disabled={isTesting}
                    aria-label={`Test ${m.name}`}
                    className={`shrink-0 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1 text-[10px] font-bold text-ink/60 transition hover:border-emerald-500 hover:text-emerald-600 disabled:opacity-50 ${FOCUS_RING}`}
                  >
                    {isTesting ? "Testing…" : "Test"}
                  </button>
                </div>
                {result ? (
                  <p className={`border-t border-[var(--ui-line)] px-3 py-1.5 text-[11px] font-semibold ${result.ok ? "text-emerald-600" : "text-coral"}`}>
                    {result.ok ? `✓ ${result.detail} · ${result.latency_ms}ms` : `✗ ${result.detail}`}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--ui-line)] pt-3">
          <p className="text-[11px] text-ink/45">{saveHint}</p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSelectedId(savedId)}
              disabled={!dirty || busySave}
              className="btn-secondary !px-3 !py-1.5 disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={!dirty || busySave}
              className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
            >
              {busySave ? "Saving…" : selectedId ? "Save model" : "Save rule-based"}
            </button>
          </div>
        </div>

        {message ? (
          <p className={`mt-2 text-[12px] font-semibold ${message.ok ? "text-emerald-600" : "text-coral"}`}>
            {message.text}
          </p>
        ) : null}

        <p className="mt-2 text-[11px] text-ink/45">
          Rules always run first. The model is only asked when a Promotion photo is attached, and its verdict is
          advice only — it never blocks publishing. Tenants never see this value.
        </p>
      </section>

      <div id="llm-models">
        <LlmsPage />
      </div>
    </div>
  );
}
