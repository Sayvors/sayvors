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
}

interface AiConfig {
  banner_vision_model: string | null;
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
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [busyTest, setBusyTest] = useState(false);
  const [test, setTest] = useState<ModelTestResult | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    Promise.all([
      adminFetch<SavedModel[]>("/api/v1/admin/models"),
      adminFetch<AiConfig>("/api/v1/admin/config/ai"),
    ])
      .then(([modelList, cfg]) => {
        setModels(modelList.filter((m) => m.enabled));
        setConfig(cfg);
        setSelected(cfg.banner_vision_model ?? "");
        setTest(null);
      })
      .catch((e) => setMessage({ ok: false, text: String(e) }));
  }, []);

  useEffect(() => { load(); }, [load]);

  const chosen = models.find((m) => m.id === selected) ?? null;

  async function runTest() {
    if (!chosen) return;
    setBusyTest(true);
    setTest(null);
    try {
      const res = await adminFetch<ModelTestResult>(
        `/api/v1/admin/llm/${chosen.provider}/models/${encodeURIComponent(chosen.id)}/test`,
        { method: "POST" }
      );
      setTest(res);
    } catch (e) {
      setTest({
        model_id: chosen.id, ok: false, latency_ms: 0,
        detail: e instanceof Error ? e.message : "Test failed.", reply: "",
      });
    } finally {
      setBusyTest(false);
    }
  }

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      const saved = await adminFetch<AiConfig>("/api/v1/admin/config/ai", {
        method: "PUT",
        body: JSON.stringify({ banner_vision_model: selected }),
      });
      setConfig(saved);
      setMessage({ ok: true, text: "Saved. Tenants will use this model for the photo check." });
    } catch (e) {
      setMessage({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">Intelligence · AI image check</p>
        <h1 className="mt-1 text-[26px] font-bold leading-none tracking-tight text-ink">Banner &amp; promotion photo check</h1>
        <p className="mt-2 max-w-[680px] text-[13px] font-medium leading-relaxed text-ink/60">
          Pick the vision model used when a tenant uploads a Promotion (banner) photo. Add or replace
          provider keys and models on the LLMs page below — they are the same catalog.
        </p>
      </div>

      <section className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[16px] font-bold text-ink">Vision model</h2>
            <p className="mt-0.5 text-[12px] text-ink/50">
              Only enabled, saved models can be chosen. Leave empty for rule-based only.
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <select
            value={selected}
            onChange={(e) => { setSelected(e.target.value); setTest(null); }}
            className="input-field min-w-[320px] flex-1"
          >
            <option value="">— rule-based check only (no LLM)</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · {m.provider}/{m.api_model}
              </option>
            ))}
            {selected && !models.some((m) => m.id === selected) ? (
              <option value={selected}>{selected} (disabled / missing)</option>
            ) : null}
          </select>
          <button
            type="button"
            onClick={() => void runTest()}
            disabled={!chosen || busyTest}
            className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
          >
            {busyTest ? "Testing…" : "Test"}
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={busy}
            className="btn-primary !px-3 !py-1.5 disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
        {test ? (
          <p className={`mt-2 text-[12px] font-semibold ${test.ok ? "text-emerald-600" : "text-coral"}`}>
            {test.ok ? `✓ ${test.detail} (${test.latency_ms}ms)` : `✗ ${test.detail}`}
          </p>
        ) : null}
        {message ? (
          <p className={`mt-2 text-[12px] font-semibold ${message.ok ? "text-emerald-600" : "text-coral"}`}>
            {message.text}
          </p>
        ) : null}
        <dl className="mt-3 space-y-1 text-[12px]">
          <div className="flex gap-2">
            <dt className="w-32 shrink-0 text-ink/45">Current</dt>
            <dd className="font-mono text-ink">
              {config?.banner_vision_model ? (
                <>
                  {config.banner_vision_model}
                  <span className="ml-2 text-ink/45">
                    ({models.find((m) => m.id === config.banner_vision_model)?.name ?? "saved model"})
                  </span>
                </>
              ) : "— (rule-based only)"}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-32 shrink-0 text-ink/45">Last updated</dt>
            <dd className="text-ink/70">
              {config?.updated_at ? new Date(config.updated_at).toLocaleString() : "—"}
            </dd>
          </div>
        </dl>
        <p className="mt-2 text-[11px] text-ink/45">
          Empty = rule-based check only (format, size, shape, sharpness, exposure), no LLM cost.
          Tenants never see this value.
        </p>
      </section>

      <LlmsPage />
    </div>
  );
}