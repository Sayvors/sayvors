"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchLeadSettings, updateLeadSettings, type LeadSettings } from "@/lib/api-leads";

/*
 * Owner controls for follow-up cadence and lead escalation.
 *
 * Every value here is clamped server-side by normalize_lead_settings; this
 * form only sends them. The response echoes the clamped values back, so what
 * you see after saving is what the engine actually uses -- an out-of-range
 * input is silently corrected rather than rejected, and the UI reflects the
 * correction instead of pretending it failed.
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";
const FOCUS =
  "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

type Status = "idle" | "loading" | "saving" | "saved" | "error";

type Field = {
  key: keyof LeadSettings;
  label: string;
  hint: string;
  min: number;
  max: number;
};

const FOLLOWUP_FIELDS: Field[] = [
  { key: "first_nudge_minutes", label: "First nudge (minutes)", hint: "5–60", min: 5, max: 60 },
  { key: "second_followup_hours", label: "Second follow-up (hours)", hint: "2–168", min: 2, max: 168 },
  { key: "final_followup_hours", label: "Final follow-up (hours)", hint: "12–336", min: 12, max: 336 },
  { key: "max_attempts", label: "Max attempts", hint: "0–4 · 0 disables the sequence", min: 0, max: 4 },
];

const ESCALATION_FIELDS: Field[] = [
  {
    key: "escalation_threshold",
    label: "Escalate after (cycles)",
    hint: "1–10 · unanswered AI replies before a human is emailed",
    min: 1,
    max: 10,
  },
  {
    key: "escalation_resume_hours",
    label: "AI resumes after (hours)",
    hint: "1–336 · how long the AI stays silent if nobody acts",
    min: 1,
    max: 336,
  },
  {
    key: "escalation_reminder_hours",
    label: "Reminder after (hours)",
    hint: "1–72 · one reminder only, then never again",
    min: 1,
    max: 72,
  },
];

export default function LeadSettingsPanel() {
  const [settings, setSettings] = useState<LeadSettings | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);
  const [emailsText, setEmailsText] = useState("");

  // Fetch without touching state synchronously -- doing so inside the mount
  // effect is a cascading render. Initial status is already "loading"; a retry
  // sets it explicitly through `retry`.
  const load = useCallback(() => {
    fetchLeadSettings()
      .then((s) => {
        setSettings(s);
        setEmailsText((s.escalation_emails ?? []).join(", "));
        setStatus("idle");
      })
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Could not load settings.");
        setStatus("error");
      });
  }, []);

  const retry = useCallback(() => {
    setStatus("loading");
    setError(null);
    load();
  }, [load]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (patch: Partial<LeadSettings>) => {
    if (status === "saving") return;
    setStatus("saving");
    setError(null);
    try {
      const saved = await updateLeadSettings(patch);
      setSettings(saved);
      setEmailsText((saved.escalation_emails ?? []).join(", "));
      setStatus("saved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.");
      setStatus("error");
    }
  };

  const numberField = (f: Field) => (
    <div key={String(f.key)}>
      <label className="block text-[12px] font-semibold text-[var(--ui-ink-2)]">
        {f.label}
      </label>
      <input
        type="number"
        min={f.min}
        max={f.max}
        value={settings ? String(settings[f.key]) : ""}
        disabled={status === "loading" || status === "saving"}
        onChange={(e) => {
          const next = Number(e.target.value);
          setSettings((s) => (s ? { ...s, [f.key]: next } : s));
        }}
        onBlur={(e) => {
          const next = Number(e.target.value);
          if (Number.isFinite(next) && settings && next !== settings[f.key]) {
            void save({ [f.key]: next } as Partial<LeadSettings>);
          }
        }}
        className={`mt-1 h-9 w-full rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[13px] tabular-nums ${INK} ${FOCUS} disabled:opacity-60`}
      />
      <p className={`mt-1 text-[11px] ${INK2}`}>{f.hint}</p>
    </div>
  );

  if (status === "loading") {
    return <p className={`text-[13px] ${INK2}`}>Loading settings…</p>;
  }

  if (status === "error" && !settings) {
    return (
      <div className="rounded-[10px] border border-coral/30 bg-coral/5 p-4">
        <p className="text-[13px] font-semibold text-coral">{error}</p>
        <button
          type="button"
          onClick={retry}
          className={`mt-2 rounded-[8px] border border-[var(--ui-line)] px-3 py-1 text-[12px] font-semibold ${INK} ${FOCUS}`}
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className={`text-[14px] font-bold ${INK}`}>Follow-ups</h3>
        <p className={`mt-0.5 text-[12px] ${INK2}`}>
          Only qualified leads are followed up — a conversation that never showed buying intent
          is left alone.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {FOLLOWUP_FIELDS.map(numberField)}
        </div>
      </div>

      <div>
        <h3 className={`text-[14px] font-bold ${INK}`}>Quiet hours</h3>
        <p className={`mt-0.5 text-[12px] ${INK2}`}>
          Proactive nudges wait until this window ends. Customer questions are still answered
          immediately at any hour.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div>
            <label className="block text-[12px] font-semibold text-[var(--ui-ink-2)]">
              Quiet start (hour)
            </label>
            <input
              type="number"
              min={0}
              max={23}
              value={settings ? String(settings.quiet_start_hour) : ""}
              disabled={status === "saving"}
              onChange={(e) =>
                setSettings((s) => (s ? { ...s, quiet_start_hour: Number(e.target.value) } : s))
              }
              onBlur={(e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v) && settings && v !== settings.quiet_start_hour) {
                  void save({ quiet_start_hour: v });
                }
              }}
              className={`mt-1 h-9 w-full rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[13px] tabular-nums ${INK} ${FOCUS} disabled:opacity-60`}
            />
            <p className={`mt-1 text-[11px] ${INK2}`}>0–23</p>
          </div>
          <div>
            <label className="block text-[12px] font-semibold text-[var(--ui-ink-2)]">
              Quiet end (hour)
            </label>
            <input
              type="number"
              min={0}
              max={23}
              value={settings ? String(settings.quiet_end_hour) : ""}
              disabled={status === "saving"}
              onChange={(e) =>
                setSettings((s) => (s ? { ...s, quiet_end_hour: Number(e.target.value) } : s))
              }
              onBlur={(e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v) && settings && v !== settings.quiet_end_hour) {
                  void save({ quiet_end_hour: v });
                }
              }}
              className={`mt-1 h-9 w-full rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[13px] tabular-nums ${INK} ${FOCUS} disabled:opacity-60`}
            />
            <p className={`mt-1 text-[11px] ${INK2}`}>0–23</p>
          </div>
          <div>
            <label className="block text-[12px] font-semibold text-[var(--ui-ink-2)]">
              Timezone
            </label>
            <input
              type="text"
              value={settings?.timezone ?? ""}
              disabled={status === "saving"}
              onChange={(e) =>
                setSettings((s) => (s ? { ...s, timezone: e.target.value } : s))
              }
              onBlur={(e) => {
                const v = e.target.value.trim();
                if (v && settings && v !== settings.timezone) void save({ timezone: v });
              }}
              placeholder="UTC"
              className={`mt-1 h-9 w-full rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[13px] ${INK} ${FOCUS} disabled:opacity-60`}
            />
            <p className={`mt-1 text-[11px] ${INK2}`}>e.g. Asia/Riyadh · unknown zones fall back to UTC</p>
          </div>
        </div>
      </div>

      <div>
        <h3 className={`text-[14px] font-bold ${INK}`}>Escalation</h3>
        <p className={`mt-0.5 text-[12px] ${INK2}`}>
          When the customer keeps writing after the AI replies, the thread is handed to a human
          and the AI stops answering it.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {ESCALATION_FIELDS.map(numberField)}
        </div>
      </div>

      <div>
        <label className="block text-[12px] font-semibold text-[var(--ui-ink-2)]">
          Escalation recipients
        </label>
        <input
          type="text"
          value={emailsText}
          disabled={status === "saving"}
          onChange={(e) => setEmailsText(e.target.value)}
          onBlur={() => {
            const list = emailsText
              .split(/[,\s]+/)
              .map((e) => e.trim())
              .filter(Boolean);
            const current = settings?.escalation_emails ?? [];
            const same =
              list.length === current.length &&
              [...list].sort().every((e, i) => e === [...current].sort()[i]);
            if (!same) void save({ escalation_emails: list });
          }}
          placeholder="Leave empty to email the account owner's signup address"
          className={`mt-1 h-9 w-full rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[13px] ${INK} ${FOCUS} disabled:opacity-60`}
        />
        <p className={`mt-1 text-[11px] ${INK2}`}>
          Comma separated, up to 10. Empty means your own account email receives every
          escalation.
        </p>
      </div>

      <div className="flex items-center gap-3 border-t border-[var(--ui-line)] pt-4" aria-live="polite">
        <p className={`text-[12px] font-semibold ${status === "error" ? "text-coral" : INK2}`}>
          {status === "saving" && "Saving…"}
          {status === "saved" && "Saved. These apply to the next reply."}
          {status === "error" && (error ?? "Could not save.")}
        </p>
      </div>
    </div>
  );
}