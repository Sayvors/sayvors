"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchLeadSettings, updateLeadSettings, type LeadSettings } from "@/lib/api-leads";

/*
 * Lead follow-up + escalation controls, rendered as a section on /dashboard/settings.
 *
 * Design: identical white-card treatment as the other configuration tabs — one
 * solid surface, a separated header, hairline rules between groups, near-zero
 * radius. These are operations settings, so structure comes from rules and
 * alignment rather than from nested rounded cards.
 *
 * Every value is clamped server-side by normalize_lead_settings. This form
 * only sends them, then writes the response back over local state — so an
 * out-of-range input comes back corrected and the UI shows what the engine
 * actually uses instead of pretending the save failed.
 */

type Status = "idle" | "loading" | "saving" | "saved" | "error";

const INK = "text-ink dark:text-fog";
const INK2 = "text-ink/50 dark:text-fog/50";
const LABEL = "text-ink/70 dark:text-fog/70";
const HAIRLINE = "border-ink/[0.08] dark:border-fog/[0.08]";
const RULE = "border-ink/[0.06] dark:border-fog/[0.06]";
const FOCUS =
  "focus-visible:outline focus-visible:outline-[2px] focus-visible:outline-offset-[-1px] focus-visible:outline-ink dark:focus-visible:outline-fog";

const inputCls =
  `h-8 w-full rounded-[2px] border ${HAIRLINE} bg-white px-2 text-[13px] tabular-nums ${INK} outline-none transition focus:border-deep-violet/40 disabled:opacity-50 dark:bg-ink ${FOCUS}`;

/** One titled group inside the section, split by a hairline rather than a gap. */
function Group({
  title,
  note,
  children,
}: {
  title: string;
  note: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`border-t ${RULE} pt-5 first:border-t-0 first:pt-0`}>
      <div className="mb-3.5">
        <h3 className="text-[10px] font-bold uppercase tracking-[0.1em] text-ink/35 dark:text-fog/35">
          {title}
        </h3>
        <p className={`mt-1.5 max-w-3xl text-[12px] leading-relaxed ${INK2}`}>{note}</p>
      </div>
      {children}
    </div>
  );
}

function Num({
  label,
  hint,
  value,
  min,
  max,
  suffix,
  disabled,
  onChange,
}: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  suffix: string;
  disabled: boolean;
  onChange: (n: number, commit?: boolean) => void;
}) {
  return (
    <label className="block">
      <span className={`block text-[12px] font-medium ${LABEL}`}>{label}</span>
      <span className="mt-1 flex items-stretch">
        <input
          type="number"
          min={min}
          max={max}
          value={String(value)}
          disabled={disabled}
          onChange={(e) => {
            const n = Number(e.target.value);
            if (Number.isFinite(n)) onChange(n);
          }}
          onBlur={(e) => {
            const n = Number(e.target.value);
            if (Number.isFinite(n) && n !== value) onChange(n, true);
          }}
          className={inputCls}
        />
        <span
          aria-hidden
          className={`flex shrink-0 items-center border-y border-r ${HAIRLINE} bg-[#f7f7f9] dark:bg-fog/[0.08] px-2 text-[11px] font-medium ${INK2}`}
        >
          {suffix}
        </span>
      </span>
      <span className="mt-1 block text-[11px] text-ink/50 dark:text-fog/50">
        {hint} · allowed {min}–{max}
      </span>
    </label>
  );
}

export default function LeadSettingsSection() {
  const [settings, setSettings] = useState<LeadSettings | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);
  const [emailsText, setEmailsText] = useState("");

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

  const busy = status === "saving" || status === "loading";

  if (status === "loading") {
    return <p className={`text-[13px] ${INK2}`}>Loading lead settings…</p>;
  }

  if (!settings) {
    return (
      <div className={`rounded-[3px] border ${HAIRLINE} bg-white p-5 dark:bg-ink`}>
        <p className="text-[13px] font-semibold text-coral">{error ?? "Could not load settings."}</p>
        <button
          type="button"
          onClick={retry}
          className={`mt-3 rounded-[2px] border ${HAIRLINE} bg-white px-3 py-1.5 text-[12px] font-semibold ${INK} transition hover:bg-ink/[0.03] dark:bg-ink dark:hover:bg-fog/[0.06] ${FOCUS}`}
        >
          Retry
        </button>
      </div>
    );
  }

  const set =
    (key: keyof LeadSettings) =>
    (n: number, commit = false) => {
      setSettings((s) => (s ? { ...s, [key]: n } : s));
      if (commit) void save({ [key]: n } as Partial<LeadSettings>);
    };

  return (
    <section className={`rounded-[3px] border ${HAIRLINE} bg-white dark:bg-ink`}>
      <header className={`flex flex-wrap items-start justify-between gap-3 border-b ${RULE} px-5 py-4`}>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-ink/35 dark:text-fog/35">
            Follow-up · Escalation
          </p>
          <h2 className="mt-1 text-[15px] font-bold text-ink dark:text-fog">
            Lead follow-up &amp; escalation
          </h2>
          <p className={`mt-1 max-w-3xl text-[12px] leading-relaxed ${INK2}`}>
            When the AI follows up on a lead, and when it stops and hands the conversation to a
            person. Applies to the next reply — no restart needed.
          </p>
        </div>
        <span
          role="status"
          aria-live="polite"
          className={`shrink-0 pt-0.5 text-[11px] font-semibold ${
            status === "error" ? "text-coral" : status === "saved" ? "text-emerald-600" : INK2
          }`}
        >
          {status === "saving" && "Saving…"}
          {status === "saved" && "Saved"}
          {status === "error" && (error ?? "Could not save")}
        </span>
      </header>

      <div className="space-y-5 px-5 py-5">
        <Group
          title="Follow-up cadence"
          note="Only leads that showed buying intent are followed up — a conversation that never asked about price, availability or booking is left alone."
        >
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Num
              label="First nudge"
              hint="After the reply that asks a question"
              value={settings.first_nudge_minutes}
              min={5}
              max={60}
              suffix="min"
              disabled={busy}
              onChange={set("first_nudge_minutes")}
            />
            <Num
              label="Second follow-up"
              hint="After the first nudge goes out"
              value={settings.second_followup_hours}
              min={2}
              max={168}
              suffix="h"
              disabled={busy}
              onChange={set("second_followup_hours")}
            />
            <Num
              label="Final follow-up"
              hint="After the second goes out"
              value={settings.final_followup_hours}
              min={12}
              max={336}
              suffix="h"
              disabled={busy}
              onChange={set("final_followup_hours")}
            />
            <Num
              label="Attempt cap"
              hint="0 switches the whole sequence off"
              value={settings.max_attempts}
              min={0}
              max={4}
              suffix="max"
              disabled={busy}
              onChange={set("max_attempts")}
            />
          </div>
        </Group>

        <Group
          title="Quiet hours"
          note="Proactive nudges wait until this window ends. Customer questions are answered immediately at any hour — only messages nobody asked for are held back."
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Num
              label="Quiet starts"
              hint="Hour, 24h clock"
              value={settings.quiet_start_hour}
              min={0}
              max={23}
              suffix=":00"
              disabled={busy}
              onChange={set("quiet_start_hour")}
            />
            <Num
              label="Quiet ends"
              hint="Hour, 24h clock"
              value={settings.quiet_end_hour}
              min={0}
              max={23}
              suffix=":00"
              disabled={busy}
              onChange={set("quiet_end_hour")}
            />
            <label className="block">
              <span className={`block text-[12px] font-medium ${LABEL}`}>Timezone</span>
              <input
                type="text"
                value={settings.timezone}
                disabled={busy}
                placeholder="UTC"
                onChange={(e) => setSettings((s) => (s ? { ...s, timezone: e.target.value } : s))}
                onBlur={(e) => {
                  const v = e.target.value.trim();
                  if (v && v !== settings.timezone) void save({ timezone: v });
                }}
                className={`mt-1 ${inputCls.replace("tabular-nums", "")}`}
              />
              <span className="mt-1 block text-[11px] text-ink/50 dark:text-fog/50">
                e.g. Asia/Riyadh · unknown zones fall back to UTC
              </span>
            </label>
          </div>
        </Group>

        <Group
          title="Escalation"
          note="When a customer keeps writing after the AI replies, the thread is handed to a person and the AI stops answering it. That silence is the point — it is also why the resume window exists."
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Num
              label="Escalate after"
              hint="Unanswered AI replies in a row"
              value={settings.escalation_threshold}
              min={1}
              max={10}
              suffix="cycles"
              disabled={busy}
              onChange={set("escalation_threshold")}
            />
            <Num
              label="AI resumes after"
              hint="With no human action"
              value={settings.escalation_resume_hours}
              min={1}
              max={336}
              suffix="h"
              disabled={busy}
              onChange={set("escalation_resume_hours")}
            />
            <Num
              label="Remind after"
              hint="One reminder only, then never"
              value={settings.escalation_reminder_hours}
              min={1}
              max={72}
              suffix="h"
              disabled={busy}
              onChange={set("escalation_reminder_hours")}
            />
          </div>

          <div className="mt-4">
            <label className={`block text-[12px] font-medium ${LABEL}`}>
              Escalation recipients
            </label>
            <input
              type="text"
              value={emailsText}
              disabled={busy}
              placeholder="Empty = email the account owner's signup address"
              onChange={(e) => setEmailsText(e.target.value)}
              onBlur={() => {
                const list = emailsText.split(/[,\s]+/).map((e) => e.trim()).filter(Boolean);
                const current = settings.escalation_emails ?? [];
                const a = [...list].sort();
                const b = [...current].sort();
                if (a.length !== b.length || !a.every((e, i) => e === b[i])) {
                  void save({ escalation_emails: list });
                }
              }}
              className={`mt-1 ${inputCls.replace("tabular-nums", "")}`}
            />
            <span className="mt-1 block text-[11px] text-ink/50 dark:text-fog/50">
              Comma separated, up to 10. With this empty every escalation goes to the email on the
              account — nothing to configure.
            </span>
          </div>
        </Group>
      </div>
    </section>
  );
}