"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchLeadSettings, updateLeadSettings, type LeadSettings } from "@/lib/api-leads";
import { apiFetch } from "@/lib/api-rag";
import SettingHelp from "@/components/settings/SettingHelp";

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

/** One row of GET /api/v1/team/members — owner and invitees alike. */
type TeamMember = { email: string; name?: string | null; status?: string | null };

/** The API caps escalation_emails at 10; the UI refuses before asking. */
const MAX_RECIPIENTS = 10;

/**
 * Common IANA zones offered in the timezone dropdown.
 *
 * The backend accepts any zone the server can load, so this is a convenience
 * list, not a validation set: a tenant in a region not here types theirs and
 * it works. Grouped roughly by where a business like ours actually operates.
 */
const TIMEZONES = [
  "Asia/Riyadh",
  "Asia/Dubai",
  "Asia/Qatar",
  "Asia/Kuwait",
  "Asia/Bahrain",
  "Asia/Muscat",
  "Asia/Baghdad",
  "Africa/Cairo",
  "Africa/Casablanca",
  "Africa/Lagos",
  "Europe/Istanbul",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Karachi",
  "Asia/Kolkata",
  "Asia/Dhaka",
  "Asia/Bangkok",
  "Asia/Singapore",
  "Asia/Jakarta",
  "Asia/Manila",
  "Asia/Hong_Kong",
  "Asia/Shanghai",
  "Australia/Sydney",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Sao_Paulo",
  "America/Mexico_City",
  "Pacific/Auckland",
  "UTC",
];

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
  help,
  children,
}: {
  title: string;
  note: string;
  help?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className={`border-t ${RULE} pt-5 first:border-t-0 first:pt-0`}>
      <div className="mb-3.5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-[10px] font-bold uppercase tracking-[0.1em] text-ink/35 dark:text-fog/35">
            {title}
          </h3>
          <p className={`mt-1.5 max-w-3xl text-[12px] leading-relaxed ${INK2}`}>{note}</p>
        </div>
        {help}
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
  onChange: (n: number) => void;
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

const CADENCE_PHRASES = [
  "First nudge waits after a reply that asks a question, then sends one gentle nudge.",
  "Second follow-up comes later if there's still no reply.",
  "Final follow-up is the last touch before the sequence stops.",
  "Attempt cap limits total follow-ups; 0 turns the whole sequence off.",
  "Scenario: lead asks about price -> AI replies and asks to book -> waits -> nudge -> follow-up -> final -> stops.",
];
const QUIET_PHRASES = [
  "Quiet hours let proactive nudges wait until the window ends.",
  "Customer questions are still answered any time.",
  "Set the start/end hours on a 24-hour clock and pick a timezone (UTC fallback if unknown).",
  "Scenario: a 22:00-07:00 window means a 23:30 lead waits until 07:00.",
];
const ESCALATION_PHRASES = [
  "Urgent words (\"urgent\", \"asap\", \"right now\", Arabic equivalents) escalate the thread immediately — no counter involved.",
  "Escalate after: consecutive turns where the customer came back confused. 0 disables the counter; normal follow-up questions never trip it.",
  "AI resumes after: hours of silence with no human action.",
  "Remind after: one reminder only, then never.",
  "Recipients: up to 10; empty goes to the account owner's email.",
  "Scenario: customer says \"this is urgent\" -> thread is handed to a human at once; the AI stays quiet until someone replies or the resume window passes.",
];

export default function LeadSettingsSection() {
  const [settings, setSettings] = useState<LeadSettings | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);
  // Escalation recipients are a chosen set of people, not typed text: the API
  // stores addresses, but the interface here is people, so the list is the
  // state and the text field is gone.
  const [recipients, setRecipients] = useState<string[]>([]);
  const [teamMembers, setTeamMembers] = useState<TeamMember[]>([]);
  const [selectedRecipient, setSelectedRecipient] = useState("");
  const [manualRecipient, setManualRecipient] = useState("");
  const [memberLoadError, setMemberLoadError] = useState<string | null>(null);
  // The browser's own zone, offered as a one-click correction but never
  // applied on its own: a tenant with branches across zones, or someone on a
  // VPN, must be able to ignore it.
  const [browserTz, setBrowserTz] = useState<string | null>(null);

  // Server truth vs the form. Everything the user edits lands in `draft` and is
  // only persisted by the Save button — these fields previously saved on blur,
  // so a number changed while clicking elsewhere committed with no visible
  // confirmation and no way to cancel it.
  const [draft, setDraft] = useState<LeadSettings | null>(null);

  const load = useCallback(() => {
    fetchLeadSettings()
      .then((s) => {
        setSettings(s);
        setDraft(s);
        setRecipients(s.escalation_emails ?? []);
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

  // Recipient picker and timezone suggestion are independent of the settings
  // load, so a failure here must not put the card into its error state — a
  // member without team.view can still edit every other setting on this page.
  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/v1/team/members")
      .then((d: { members?: TeamMember[] }) => {
        if (!cancelled) setTeamMembers(d.members ?? []);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setMemberLoadError(
            e instanceof Error ? e.message : "Could not load team members.",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    // Etc/UTC is what an unconfigured browser reports; offering it back as a
    // "detected" value would be a suggestion to do nothing.
    if (detected && detected !== "UTC" && detected !== "Etc/UTC") {
      setBrowserTz(detected);
    }
  }, []);

  const dirty = useMemo(() => {
    if (!settings || !draft) return false;
    if (settings.first_nudge_minutes !== draft.first_nudge_minutes) return true;
    if (settings.second_followup_hours !== draft.second_followup_hours) return true;
    if (settings.final_followup_hours !== draft.final_followup_hours) return true;
    if (settings.max_attempts !== draft.max_attempts) return true;
    if (settings.quiet_start_hour !== draft.quiet_start_hour) return true;
    if (settings.quiet_end_hour !== draft.quiet_end_hour) return true;
    if (settings.timezone !== draft.timezone) return true;
    if (settings.escalation_threshold !== draft.escalation_threshold) return true;
    if (settings.escalation_resume_hours !== draft.escalation_resume_hours) return true;
    if (settings.escalation_reminder_hours !== draft.escalation_reminder_hours) return true;
    if (settings.digest_enabled !== draft.digest_enabled) return true;
    if (settings.digest_hour !== draft.digest_hour) return true;
    if (settings.digest_max_leads !== draft.digest_max_leads) return true;
    const a = [...recipients].sort();
    const b = [...(settings.escalation_emails ?? [])].sort();
    return a.length !== b.length || !a.every((e, i) => e === b[i]);
  }, [settings, draft, recipients]);

  const discard = useCallback(() => {
    if (!settings) return;
    setDraft(settings);
    setRecipients(settings.escalation_emails ?? []);
    setStatus("idle");
    setError(null);
  }, [settings]);

  const save = async () => {
    if (status === "saving" || !draft) return;
    setStatus("saving");
    setError(null);
    try {
      const saved = await updateLeadSettings({ ...draft, escalation_emails: recipients });
      setSettings(saved);
      setDraft(saved);
      setRecipients(saved.escalation_emails ?? []);
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

  if (!settings || !draft) {
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

  const set = (key: keyof LeadSettings) => (n: number) => {
    setDraft((d) => (d ? { ...d, [key]: n } : d));
    if (status === "saved") setStatus("idle");
  };

  // One entry point for both ways of adding a recipient, so the cap and the
  // duplicate check cannot drift between the dropdown and the manual field.
  const addRecipient = (raw: string) => {
    const email = raw.trim().toLowerCase();
    if (!email || recipients.includes(email)) return;
    if (recipients.length >= MAX_RECIPIENTS) return;
    setRecipients((r) => [...r, email]);
    setManualRecipient("");
    if (status === "saved") setStatus("idle");
  };

  // 12 AM is hour 0, 12 PM is 12. Everything else is the 12-hour face value,
  // shifted by 12 when it is afternoon. Kept as a named pair so the AM/PM
  // buttons and this conversion can never disagree about which is 12.
  const digestHour24 = (hour12: number, period: "AM" | "PM") =>
    period === "AM" ? (hour12 === 12 ? 0 : hour12) : hour12 === 12 ? 12 : hour12 + 12;

  const digestHour12 = (hour24: number) => (hour24 % 12 === 0 ? 12 : hour24 % 12);
  const digestPeriod = (hour24: number): "AM" | "PM" => (hour24 < 12 ? "AM" : "PM");

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
          help={
            <SettingHelp
              ariaLabel="How lead follow-up cadence works"
              title="Follow-up cadence"
              phrases={CADENCE_PHRASES}
            />
          }
        >
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Num
              label="First nudge"
              hint="After the reply that asks a question"
              value={draft.first_nudge_minutes}
              min={5}
              max={60}
              suffix="min"
              disabled={busy}
              onChange={set("first_nudge_minutes")}
            />
            <Num
              label="Second follow-up"
              hint="After the first nudge goes out"
              value={draft.second_followup_hours}
              min={2}
              max={168}
              suffix="h"
              disabled={busy}
              onChange={set("second_followup_hours")}
            />
            <Num
              label="Final follow-up"
              hint="After the second goes out"
              value={draft.final_followup_hours}
              min={12}
              max={336}
              suffix="h"
              disabled={busy}
              onChange={set("final_followup_hours")}
            />
            <Num
              label="Attempt cap"
              hint="0 switches the whole sequence off"
              value={draft.max_attempts}
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
          help={
            <SettingHelp
              ariaLabel="How quiet hours work"
              title="Quiet hours"
              phrases={QUIET_PHRASES}
            />
          }
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Num
              label="Quiet starts"
              hint="Hour, 24h clock"
              value={draft.quiet_start_hour}
              min={0}
              max={23}
              suffix=":00"
              disabled={busy}
              onChange={set("quiet_start_hour")}
            />
            <Num
              label="Quiet ends"
              hint="Hour, 24h clock"
              value={draft.quiet_end_hour}
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
                list="sayvors-timezones"
                value={draft.timezone}
                disabled={busy}
                placeholder="UTC"
                onChange={(e) => {
                  setDraft((d) => (d ? { ...d, timezone: e.target.value } : d));
                  if (status === "saved") setStatus("idle");
                }}
                className={`mt-1 ${inputCls.replace("tabular-nums", "")}`}
              />
              <datalist id="sayvors-timezones">
                {TIMEZONES.map((tz) => (
                  <option key={tz} value={tz} />
                ))}
              </datalist>
              <span className="mt-1 block text-[11px] text-ink/50 dark:text-fog/50">
                Pick from the list or type any IANA zone. Unknown zones fall back to UTC.
              </span>
              {/* Offered only when it would change something. Suggesting the
                  value the field already holds is noise, and a tenant whose
                  saved zone differs from the browser's needs a real choice. */}
              {browserTz && browserTz !== draft.timezone && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setDraft((d) => (d ? { ...d, timezone: browserTz } : d));
                    if (status === "saved") setStatus("idle");
                  }}
                  className={`mt-1.5 inline-flex items-center rounded-[2px] border ${HAIRLINE} bg-white px-2 py-1 text-[11px] font-semibold ${INK2} transition hover:bg-ink/[0.03] disabled:opacity-40 dark:bg-ink dark:hover:bg-fog/[0.06] ${FOCUS}`}
                >
                  Use {browserTz}
                </button>
              )}
            </label>
          </div>
        </Group>

        <Group
          title="Escalation"
          note="The AI answers normal follow-up questions indefinitely. It only steps aside when the customer says it is urgent, or when the confusion counter you enable below trips."
          help={
            <SettingHelp
              ariaLabel="How lead escalation works"
              title="Escalation"
              phrases={ESCALATION_PHRASES}
            />
          }
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Num
              label="Escalate after"
              hint="Confused customer turns in a row · 0 = never"
              value={draft.escalation_threshold}
              min={0}
              max={10}
              suffix="cycles"
              disabled={busy}
              onChange={set("escalation_threshold")}
            />
            <Num
              label="AI resumes after"
              hint="With no human action"
              value={draft.escalation_resume_hours}
              min={1}
              max={336}
              suffix="h"
              disabled={busy}
              onChange={set("escalation_resume_hours")}
            />
            <Num
              label="Remind after"
              hint="One reminder only, then never"
              value={draft.escalation_reminder_hours}
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
            {memberLoadError ? (
              <p className="mt-1 text-[11px] text-ink/50 dark:text-fog/50">
                Could not load the team list — add addresses by hand below.
              </p>
            ) : null}
            <div className="mt-1 flex flex-wrap gap-1.5">
              <select
                value={selectedRecipient}
                disabled={busy || teamMembers.length === 0}
                onChange={(e) => setSelectedRecipient(e.target.value)}
                className={`h-8 min-w-0 flex-1 rounded-[2px] border ${HAIRLINE} bg-white px-2 text-[13px] ${INK} outline-none focus:border-deep-violet/40 disabled:opacity-50 dark:bg-ink`}
              >
                <option value="">
                  {teamMembers.length === 0 ? "No team members found" : "Add a person…"}
                </option>
                {teamMembers
                  .filter((m) => !recipients.includes(m.email))
                  .map((m) => (
                    <option key={m.email} value={m.email}>
                      {m.name && m.name !== m.email ? `${m.name} — ${m.email}` : m.email}
                    </option>
                  ))}
              </select>
              <button
                type="button"
                disabled={busy || selectedRecipient === ""}
                onClick={() => {
                  addRecipient(selectedRecipient);
                  setSelectedRecipient("");
                }}
                className={`rounded-[2px] bg-deep-violet px-4 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40 ${FOCUS}`}
              >
                Add
              </button>
            </div>

            {/* Manual entry stays for one reason: a tenant can point escalation
                at someone who is not in the workspace at all. It is a single
                address and a click, not a comma-separated list to parse. */}
            <div className="mt-2 flex flex-wrap gap-1.5">
              <input
                type="email"
                value={manualRecipient}
                disabled={busy}
                placeholder="Or an address outside this workspace"
                onChange={(e) => setManualRecipient(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addRecipient(manualRecipient);
                  }
                }}
                className={`h-8 min-w-0 flex-1 rounded-[2px] border ${HAIRLINE} bg-white px-2 text-[13px] ${INK} outline-none focus:border-deep-violet/40 disabled:opacity-50 dark:bg-ink`}
              />
              <button
                type="button"
                disabled={busy || manualRecipient.trim() === ""}
                onClick={() => addRecipient(manualRecipient)}
                className={`rounded-[2px] border ${HAIRLINE} bg-white px-4 text-[12px] font-bold ${INK} transition hover:bg-ink/[0.03] disabled:opacity-40 dark:bg-ink dark:hover:bg-fog/[0.06] ${FOCUS}`}
              >
                Add address
              </button>
            </div>

            {recipients.length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Selected recipients">
                {recipients.map((email) => (
                  <li
                    key={email}
                    className={`flex items-center gap-1 rounded-[2px] border ${HAIRLINE} bg-ink/[0.02] py-1 pl-2 pr-1 text-[12px] dark:bg-fog/[0.03]`}
                  >
                    <span className="max-w-[18rem] truncate text-ink/80 dark:text-fog/80">
                      {email}
                    </span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setRecipients((r) => r.filter((x) => x !== email));
                        if (status === "saved") setStatus("idle");
                      }}
                      aria-label={`Remove ${email}`}
                      className={`rounded-[1px] px-1 text-[13px] leading-none ${INK2} transition hover:text-coral disabled:opacity-40 ${FOCUS}`}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}

            <span className="mt-1 block text-[11px] text-ink/50 dark:text-fog/50">
              Up to 10. Empty means every escalation goes to the account owner&apos;s own signup
              address — nothing to configure.
            </span>
          </div>
        </Group>

        <Group
          title="Daily digest"
          note="One email a day listing the leads still waiting on you. Qualified and follow-up leads only — anything converted, lost, or opted out is left out, and nothing is sent when there is nothing waiting."
        >
          <label className="flex cursor-pointer items-start gap-2.5">
            <input
              type="checkbox"
              checked={draft.digest_enabled}
              disabled={busy}
              onChange={(e) => {
                setDraft((d) => (d ? { ...d, digest_enabled: e.target.checked } : d));
                if (status === "saved") setStatus("idle");
              }}
              className="mt-0.5 h-4 w-4 rounded text-deep-violet focus:ring-deep-violet/40"
            />
            <span>
              <span className={`block text-[13px] font-semibold ${INK}`}>
                Email me the pending leads each morning
              </span>
              <span className={`block text-[11px] ${INK2}`}>
                Goes to the same people as escalation emails. Off by default — turn it on when you
                want the rollup.
              </span>
            </span>
          </label>

          {/* Disabled-until-enabled, so the two extra controls below never look
              like live settings while the digest is off. */}
          <div
            className={`mt-4 grid gap-4 sm:grid-cols-2 ${draft.digest_enabled ? "" : "opacity-50"}`}
          >
            <div>
              <span className={`block text-[12px] font-medium ${LABEL}`}>Send at</span>
              <div className="mt-1 flex items-stretch">
                <select
                  value={digestHour12(draft.digest_hour)}
                  disabled={busy || !draft.digest_enabled}
                  onChange={(e) =>
                    setDraft((d) =>
                      d
                        ? {
                            ...d,
                            digest_hour: digestHour24(
                              Number(e.target.value),
                              digestPeriod(d.digest_hour),
                            ),
                          }
                        : d,
                    )
                  }
                  className={`h-8 w-full rounded-l-[2px] border ${HAIRLINE} bg-white px-2 text-[13px] tabular-nums ${INK} outline-none focus:border-deep-violet/40 disabled:opacity-50 dark:bg-ink`}
                >
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((h) => (
                    <option key={h} value={h}>
                      {h}
                    </option>
                  ))}
                </select>
                <div
                  role="radiogroup"
                  aria-label="AM or PM"
                  className="flex"
                >
                  {(["AM", "PM"] as const).map((period) => {
                    const on = digestPeriod(draft.digest_hour) === period;
                    return (
                      <button
                        key={period}
                        type="button"
                        role="radio"
                        aria-checked={on}
                        disabled={busy || !draft.digest_enabled}
                        onClick={() =>
                          setDraft((d) =>
                            d
                              ? {
                                  ...d,
                                  digest_hour: digestHour24(
                                    digestHour12(d.digest_hour),
                                    period,
                                  ),
                                }
                              : d,
                          )
                        }
                        className={`h-8 border-y border-r px-3 text-[12px] font-bold transition ${
                          on
                            ? "border-deep-violet bg-deep-violet text-white"
                            : `${HAIRLINE} bg-white ${INK2} hover:bg-ink/[0.03] dark:bg-ink dark:hover:bg-fog/[0.06]`
                        } disabled:opacity-50 ${FOCUS}`}
                      >
                        {period}
                      </button>
                    );
                  })}
                </div>
              </div>
              <span className="mt-1 block text-[11px] text-ink/50 dark:text-fog/50">
                Your timezone ({draft.timezone}) — allowed 0–23
              </span>
            </div>

            <Num
              label="How many to list"
              hint="A longer list is summarised as &ldquo;and N more&rdquo;"
              value={draft.digest_max_leads}
              min={1}
              max={100}
              suffix="leads"
              disabled={busy || !draft.digest_enabled}
              onChange={set("digest_max_leads")}
            />
          </div>
        </Group>
      </div>

      {/* Account-wide: one save for the whole card. These settings are not per
          branch, so the button says so rather than inheriting the Google tab's
          "apply to all branches" language. */}
      <footer
        className={`flex flex-wrap items-center justify-between gap-3 border-t ${RULE} px-5 py-4`}
      >
        <p className={`text-[11px] ${INK2}`}>
          {dirty
            ? "Unsaved changes — nothing is stored until you save."
            : "These settings apply to the whole account, not per branch."}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={discard}
            disabled={!dirty || busy}
            className={`rounded-[2px] border ${HAIRLINE} bg-white px-3.5 py-2 text-[12px] font-bold ${INK} transition hover:bg-ink/[0.03] disabled:opacity-40 dark:bg-ink dark:hover:bg-fog/[0.06] ${FOCUS}`}
          >
            Discard
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={!dirty || busy}
            className={`rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40 ${FOCUS}`}
          >
            {status === "saving" ? "Saving…" : "Save lead settings"}
          </button>
        </div>
      </footer>
    </section>
  );
}