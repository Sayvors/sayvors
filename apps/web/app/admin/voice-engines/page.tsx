"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";
import {
  ErrorState,
  PageHeader,
  Panel,
  Pill,
  SectionTitle,
} from "../admin-ui";

/* ── shapes mirror VoiceEngineStatus / VoiceEngineUpsert ───────────────── */

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
  name: string;
  [k: string]: unknown;
}

/** What the operator may edit. `api_key` is write-only: the backend never
 *  returns it, so it is never echoed back into the form. */
interface EngineForm {
  label: string;
  provider: string;
  tier: string;
  api_url: string;
  api_model: string;
  api_key: string;
  reference_id: string;
  languages: string;
  language_references: string; // "ur=<id>, hi=<id>" — parsed on save
  enabled: boolean;
}

const EMPTY_FORM: EngineForm = {
  label: "",
  provider: "",
  tier: "simple",
  api_url: "",
  api_model: "",
  api_key: "",
  reference_id: "",
  languages: "*",
  language_references: "",
  enabled: true,
};

const TIERS = ["simple", "advanced"] as const;

/**
 * A tier is the only thing a tenant ever sees — never the provider or the key.
 * That asymmetry is the whole point of this screen, so it is stated once,
 * here, rather than rediscovered per row.
 */
function tierBlurb(tier: string): string {
  return tier === "advanced"
    ? "Better quality, higher cost"
    : "Cheaper, good enough for short notes";
}

function parsePins(raw: string): Record<string, string> | null {
  const out: Record<string, string> = {};
  for (const part of raw.split(",")) {
    const [k, ...rest] = part.split("=");
    const v = rest.join("=").trim();
    const key = k.trim().toLowerCase();
    if (key && v) out[key] = v;
  }
  return Object.keys(out).length ? out : null;
}

export default function AdminVoiceEnginesPage() {
  const [engines, setEngines] = useState<VoiceEngine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, string>>({});

  // Editor state. `editing === null` means the form is closed; `editing === "new"`
  // means create, otherwise it is the engine id being edited.
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<EngineForm>(EMPTY_FORM);
  const [formError, setFormError] = useState<string | null>(null);

  const [fishOpen, setFishOpen] = useState(false);
  const [fish, setFish] = useState<FishVoice[]>([]);
  const [fishError, setFishError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEngines(await adminFetch<VoiceEngine[]>("/api/v1/admin/voice-engines"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load voice engines.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  function openNew() {
    setForm(EMPTY_FORM);
    setFormError(null);
    setEditing("new");
  }

  function openEdit(e: VoiceEngine) {
    setForm({
      label: e.label,
      provider: e.provider,
      tier: e.tier,
      api_url: e.api_url ?? "",
      api_model: e.api_model ?? "",
      // The key is never returned. Leaving this blank means "keep the stored
      // key" — an empty string clears it, per the endpoint contract.
      api_key: "",
      reference_id: e.reference_id ?? "",
      languages: e.languages ?? "*",
      language_references: e.language_references
        ? Object.entries(e.language_references)
            .map(([k, v]) => `${k}=${v}`)
            .join(", ")
        : "",
      enabled: e.enabled,
    });
    setFormError(null);
    setEditing(e.id);
  }

  async function save() {
    setFormError(null);
    if (!form.label.trim()) {
      setFormError("Label is required.");
      return;
    }
    if (!form.provider.trim()) {
      setFormError("Provider is required.");
      return;
    }
    const payload = {
      label: form.label.trim(),
      provider: form.provider.trim(),
      tier: form.tier,
      api_url: form.api_url.trim() || null,
      api_model: form.api_model.trim() || null,
      // Only sent when non-empty: the backend treats a null as "leave it".
      ...(form.api_key ? { api_key: form.api_key } : {}),
      reference_id: form.reference_id.trim() || null,
      languages: form.languages.trim() || "*",
      language_references: parsePins(form.language_references),
      enabled: form.enabled,
    };
    setBusyId(editing ?? "new");
    try {
      if (editing === "new") {
        await adminFetch("/api/v1/admin/voice-engines", {
          method: "POST",
          body: JSON.stringify(payload),
        });
      } else {
        await adminFetch(`/api/v1/admin/voice-engines/${editing}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
      }
      setEditing(null);
      await load();
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Could not save the engine.");
    } finally {
      setBusyId(null);
    }
  }

  async function remove(e: VoiceEngine) {
    if (!window.confirm(`Delete voice engine "${e.label}"? Tenants on this tier fall back to the other engine.`)) {
      return;
    }
    setBusyId(e.id);
    setError(null);
    try {
      await adminFetch(`/api/v1/admin/voice-engines/${e.id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the engine.");
    } finally {
      setBusyId(null);
    }
  }

  async function test(e: VoiceEngine) {
    setBusyId(e.id);
    setError(null);
    try {
      const res = await adminFetch<{ ok: boolean; detail?: string }>(
        `/api/v1/admin/voice-engines/${e.id}/test`,
        { method: "POST" },
      );
      setTestResult((prev) => ({
        ...prev,
        [e.id]: res.ok ? "Synthesised OK" : res.detail ?? "Failed",
      }));
    } catch (err) {
      setTestResult((prev) => ({
        ...prev,
        [e.id]: err instanceof Error ? err.message : "Failed",
      }));
    } finally {
      setBusyId(null);
    }
  }

  async function loadFish() {
    setFishOpen(true);
    setFishError(null);
    try {
      setFish(await adminFetch<FishVoice[]>("/api/v1/admin/voice-engines/fish-voices"));
    } catch (e) {
      setFishError(
        e instanceof Error
          ? e.message
          : "Could not load the fish.audio library.",
      );
      // The endpoint needs a fish engine key already stored; say so rather than
      // surfacing a bare 400 the operator cannot act on.
      if (!engines.some((x) => x.provider === "fish")) {
        setFishError(
          "Add a fish.audio voice engine with an API key first — the library is browsed with that key.",
        );
      }
    }
  }

  if (loading && engines.length === 0) {
    return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;
  }

  return (
    <div className="admin-ui">
      <PageHeader
        title="Voice engines"
        lede="Which text-to-speech engine serves each tenant tier. Tenants see the tier, never the provider or key."
        actions={
          <button
            type="button"
            onClick={openNew}
            className="admin-btn bg-deep-violet text-white hover:bg-deep-violet/90"
          >
            + Add engine
          </button>
        }
      />

      {error && (
        <div className="mb-[var(--ad-m)]">
          <ErrorState title="Voice engines unavailable" detail={error} onRetry={() => void load()} />
        </div>
      )}

      {engines.length === 0 && !error ? (
        <Panel>
          <SectionTitle>No engines configured</SectionTitle>
          <p className="text-admin-base text-ink/60">
            Without an engine, WhatsApp voice notes are sent as plain text. Add one
            per tier — "simple" and "advanced" — and each tenant tier gets the
            matching quality.
          </p>
        </Panel>
      ) : (
        <Panel>
          <SectionTitle>Configured engines ({engines.length})</SectionTitle>
          <div className="space-y-[var(--ad-xs)]">
            {engines.map((e) => (
              <div
                key={e.id}
                className="rounded-admin-ctl border border-ink/[0.07] p-[var(--ad-xs)]"
              >
                <div className="flex flex-wrap items-center gap-[var(--ad-2xs)]">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-admin-base font-bold text-ink">
                      {e.label}
                    </span>
                    <span className="block text-admin-micro text-ink/50">
                      {e.provider} · {e.tier}
                    </span>
                  </span>
                  <Pill tone={e.enabled ? "ok" : "neutral"}>
                    {e.enabled ? "enabled" : "disabled"}
                  </Pill>
                  {/* has_key is a boolean by design: the key value is never
                      returned, so there is nothing more to show. */}
                  <Pill tone={e.has_key ? "ok" : "bad"}>
                    {e.has_key ? "key set" : "no key"}
                  </Pill>
                </div>

                <p className="mt-[var(--ad-2xs)] text-admin-micro text-ink/50">
                  {tierBlurb(e.tier)}
                  {e.languages && e.languages !== "*" &&
                    ` · languages: ${e.languages}`}
                  {e.reference_id && ` · voice: ${e.reference_id}`}
                </p>

                {testResult[e.id] && (
                  <p
                    role="status"
                    className={`mt-[var(--ad-2xs)] text-admin-micro font-semibold ${
                      testResult[e.id].includes("OK") ? "text-emerald-700" : "text-coral"
                    }`}
                  >
                    Test: {testResult[e.id]}
                  </p>
                )}

                <div className="mt-[var(--ad-xs)] flex flex-wrap gap-[var(--ad-2xs)]">
                  <button
                    type="button"
                    onClick={() => void test(e)}
                    disabled={busyId !== null}
                    className="admin-btn border border-ink/10 text-ink/70 hover:bg-ink/[0.04] disabled:opacity-40"
                  >
                    {busyId === e.id ? "Testing…" : "Test"}
                  </button>
                  <button
                    type="button"
                    onClick={() => openEdit(e)}
                    disabled={busyId !== null}
                    className="admin-btn border border-ink/10 text-ink/70 hover:bg-ink/[0.04] disabled:opacity-40"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(e)}
                    disabled={busyId !== null}
                    className="admin-btn border border-coral/30 text-coral hover:bg-coral/10 disabled:opacity-40"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {/* ── editor ─────────────────────────────────────────────────────── */}
      {editing !== null && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <button
            type="button"
            aria-label="Close editor"
            onClick={() => setEditing(null)}
            className="absolute inset-0 bg-ink/30"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label={editing === "new" ? "Add voice engine" : "Edit voice engine"}
            className="admin-ui relative h-full w-full max-w-2xl overflow-y-auto border-l border-card-border bg-fog p-[var(--ad-m)]"
          >
            <div className="mb-[var(--ad-m)] flex items-start justify-between">
              <h2 className="text-admin-lg font-bold text-ink">
                {editing === "new" ? "Add voice engine" : "Edit voice engine"}
              </h2>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="admin-btn border border-ink/10 px-[var(--ad-xs)] py-1 text-admin-base text-ink/60"
              >
                Close
              </button>
            </div>

            {formError && (
              <p role="alert" className="mb-[var(--ad-s)] rounded-admin-ctl bg-coral/10 px-[var(--ad-xs)] py-[var(--ad-2xs)] text-admin-base font-medium text-coral">
                {formError}
              </p>
            )}

            <div className="space-y-[var(--ad-s)]">
              <Field label="Label" hint="Shown in the list; not exposed to tenants.">
                <input
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                  className="input-field w-full"
                  placeholder="Fish — simple tier"
                />
              </Field>

              <Field label="Provider" hint="edge | fish | any identifier your keys are filed under.">
                <input
                  value={form.provider}
                  onChange={(e) => setForm({ ...form, provider: e.target.value })}
                  className="input-field w-full"
                  placeholder="fish"
                />
              </Field>

              <Field label="Tier" hint="Tenants only ever see this.">
                <div className="flex gap-[var(--ad-2xs)]">
                  {TIERS.map((t) => (
                    <button
                      key={t}
                      type="button"
                      aria-pressed={form.tier === t}
                      onClick={() => setForm({ ...form, tier: t })}
                      className={`admin-btn border px-[var(--ad-s)] py-[var(--ad-2xs)] ${
                        form.tier === t
                          ? "border-deep-violet bg-deep-violet text-white"
                          : "border-ink/10 text-ink/70"
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </Field>

              <Field label="API key" hint="Write-only. Leave blank to keep the stored key; type an empty value to clear it.">
                <input
                  type="password"
                  value={form.api_key}
                  onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                  className="input-field w-full"
                  autoComplete="off"
                  placeholder={editing === "new" ? "required" : "leave blank to keep"}
                />
              </Field>

              <Field label="API URL" hint="Optional. Empty uses the provider default.">
                <input
                  value={form.api_url}
                  onChange={(e) => setForm({ ...form, api_url: e.target.value })}
                  className="input-field w-full"
                  placeholder="https://api.fish.audio"
                />
              </Field>

              <Field label="API model" hint="Optional. Voice name for edge; ignored by fish.">
                <input
                  value={form.api_model}
                  onChange={(e) => setForm({ ...form, api_model: e.target.value })}
                  className="input-field w-full"
                  placeholder="en-US-JennyNeural"
                />
              </Field>

              <Field
                label="Voice reference"
                hint="fish.audio reference_id — pins one persona instead of Fish picking per request."
              >
                <div className="flex gap-[var(--ad-2xs)]">
                  <input
                    value={form.reference_id}
                    onChange={(e) => setForm({ ...form, reference_id: e.target.value })}
                    className="input-field w-full"
                    placeholder="abc123def"
                  />
                  <button
                    type="button"
                    onClick={() => void loadFish()}
                    className="admin-btn shrink-0 border border-ink/10 text-ink/70 hover:bg-ink/[0.04]"
                  >
                    Browse voices
                  </button>
                </div>
              </Field>

              {fishOpen && (
                <Panel>
                  <SectionTitle>fish.audio library</SectionTitle>
                  {fishError ? (
                    <p className="text-admin-base text-ink/60">{fishError}</p>
                  ) : fish.length === 0 ? (
                    <p className="text-admin-base text-ink/60">No voices returned.</p>
                  ) : (
                    <ul className="max-h-56 space-y-[var(--ad-3xs)] overflow-y-auto">
                      {fish.map((v) => (
                        <li key={v.id}>
                          <button
                            type="button"
                            onClick={() => {
                              setForm({ ...form, reference_id: v.id });
                              setFishOpen(false);
                            }}
                            className="admin-btn w-full justify-start border border-ink/10 text-ink/70 hover:bg-ink/[0.04]"
                          >
                            {v.name ?? v.id}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </Panel>
              )}

              <Field label="Languages" hint="Comma-separated codes, or * for any.">
                <input
                  value={form.languages}
                  onChange={(e) => setForm({ ...form, languages: e.target.value })}
                  className="input-field w-full"
                  placeholder="*"
                />
              </Field>

              <Field
                label="Language pins"
                hint="Optional. One voice per language: ur=<id>, hi=<id>. Max 8."
              >
                <input
                  value={form.language_references}
                  onChange={(e) => setForm({ ...form, language_references: e.target.value })}
                  className="input-field w-full"
                  placeholder="ur=abc123, hi=def456"
                />
              </Field>

              <label className="flex items-center gap-[var(--ad-2xs)] text-admin-base text-ink/75">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                  className="h-4 w-4 accent-deep-violet"
                />
                Enabled — tenants on this tier get voice notes
              </label>
            </div>

            <div className="mt-[var(--ad-m)] flex gap-[var(--ad-2xs)]">
              <button
                type="button"
                onClick={() => void save()}
                disabled={busyId !== null}
                className="admin-btn flex-1 bg-deep-violet text-white hover:bg-deep-violet/90 disabled:opacity-40"
              >
                {busyId !== null ? "Saving…" : "Save"}
              </button>
              <button
                type="button"
                onClick={() => setEditing(null)}
                className="admin-btn border border-ink/10 text-ink/70"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── labelled field ──────────────────────────────────────────────────── */

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-[var(--ad-3xs)] block text-admin-base font-bold text-ink">
        {label}
      </label>
      {children}
      {hint && (
        <p className="mt-[var(--ad-3xs)] text-admin-micro text-ink/45">{hint}</p>
      )}
    </div>
  );
}