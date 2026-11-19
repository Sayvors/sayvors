"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

interface AiConfig {
  banner_vision_model: string | null;
  updated_at: string | null;
}

export default function AiImageCheckPage() {
  const [config, setConfig] = useState<AiConfig | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    adminFetch<AiConfig>("/api/v1/admin/config/ai")
      .then((row) => {
        setConfig(row);
        setDraft(row.banner_vision_model ?? "");
      })
      .catch((e) => setMessage({ ok: false, text: String(e) }));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      const saved = await adminFetch<AiConfig>("/api/v1/admin/config/ai", {
        method: "PUT",
        body: JSON.stringify({ banner_vision_model: draft }),
      });
      setConfig(saved);
      setDraft(saved.banner_vision_model ?? "");
      setMessage({ ok: true, text: "Saved. Tenants will use this model for the photo check." });
    } catch (e) {
      setMessage({ ok: false, text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="admin-rise flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-ink/40">Intelligence · AI image check</p>
          <h1 className="mt-1 text-[26px] font-bold leading-none tracking-tight text-ink">Banner &amp; promotion photo check</h1>
          <p className="mt-2 max-w-[680px] text-[13px] font-medium leading-relaxed text-ink/60">
            Choose the vision model used when a tenant uploads a Promotion (banner) photo to their
            Google Business Profile. The model id is never shown to tenants — they only see the
            suitability verdict and confidence.
          </p>
        </div>
      </div>

      <section className="admin-rise panel p-4 sm:p-5" style={{ animationDelay: "60ms" }}>
        <label className="mb-1.5 block text-[12px] font-bold text-ink/70" htmlFor="vision-model">
          Vision model (provider:model)
        </label>
        <input
          id="vision-model"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="e.g. gemini:gemini-2.0-flash — leave empty to disable"
          className={`w-full rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-ink placeholder:text-ink/35 focus:border-deep-violet focus:outline-none ${FOCUS_RING}`}
        />
        <p className="mt-1.5 text-[11px] leading-relaxed text-ink/45">
          Empty = rule-based check only (format, size, shape, sharpness, exposure), no LLM cost.
          Tenants never see this value.
        </p>
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={save}
            disabled={busy}
            className={`rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:opacity-90 disabled:opacity-50 ${FOCUS_RING}`}
          >
            {busy ? "Saving…" : "Save"}
          </button>
          {message ? (
            <span className={`text-[12px] font-semibold ${message.ok ? "text-emerald-700" : "text-red-700"}`}>
              {message.text}
            </span>
          ) : null}
        </div>
      </section>

      <section className="admin-rise panel p-4" style={{ animationDelay: "120ms" }}>
        <h2 className="text-[12px] font-bold uppercase tracking-[0.12em] text-ink/45">Current</h2>
        <dl className="mt-2 space-y-1.5 text-[13px]">
          <div className="flex gap-2">
            <dt className="w-40 shrink-0 text-ink/45">Vision model</dt>
            <dd className="font-mono text-ink">
              {config?.banner_vision_model || "— (rule-based only)"}
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-40 shrink-0 text-ink/45">Last updated</dt>
            <dd className="text-ink/70">
              {config?.updated_at ? new Date(config.updated_at).toLocaleString() : "—"}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
