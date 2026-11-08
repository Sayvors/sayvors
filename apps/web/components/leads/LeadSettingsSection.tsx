"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchLeadSettings, updateLeadSettings, type LeadSettings } from "@/lib/api-leads";
import {
  LEAD_CATEGORIES,
  leadCategoryLabelKnown,
  type LeadCategory,
} from "@/lib/lead-labels";
import { apiFetch } from "@/lib/api-rag";
import SettingHelp from "@/components/settings/SettingHelp";
import { useI18n } from "@/lib/i18n/I18nProvider";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

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
  const { t, locale } = useI18n();
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
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
        {hint} · {fill(t.reviews.settings.lead.rangeHint, { min: fmt(min), max: fmt(max) })}
      </span>
    </label>
  );
}

export default function LeadSettingsSection() {
  const { t, locale } = useI18n();
  const ls = t.reviews.settings.lead;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
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
        setError(e instanceof Error ? e.message : ls.loadFailed);
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
            e instanceof Error ? e.message : ls.teamFailed,
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
    const qa = [...(draft.qualified_categories ?? [])].sort();
    const qb = [...(settings.qualified_categories ?? [])].sort();
    if (qa.length !== qb.length || !qa.every((c, i) => c === qb[i])) return true;
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

  const toggleQualifiedCategory = (category: LeadCategory) => {
    setDraft((prev) => {
      if (!prev) return prev;
      const current = prev.qualified_categories ?? [];
      const next = current.includes(category)
        ? current.filter((c) => c !== category)
        : [...current, category];
      return { ...prev, qualified_categories: next };
    });
    if (status === "saved") setStatus("idle");
  };

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
      setError(e instanceof Error ? e.message : ls.saveFailed);
      setStatus("error");
    }
  };

  const busy = status === "saving" || status === "loading";

  if (status === "loading") {
    return <p className={`text-[13px] ${INK2}`}>{ls.loadSettings}</p>;
  }

  if (!settings || !draft) {
    return (
      <div className={`rounded-[3px] border ${HAIRLINE} bg-white p-5 dark:bg-ink`}>
        <p className="text-[13px] font-semibold text-coral">{error ?? ls.loadFailed}</p>
        <button
          type="button"
          onClick={retry}
          className={`mt-3 rounded-[2px] border ${HAIRLINE} bg-white px-3 py-1.5 text-[12px] font-semibold ${INK} transition hover:bg-ink/[0.03] dark:bg-ink dark:hover:bg-fog/[0.06] ${FOCUS}`}
        >
          {ls.retry}
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
            {ls.eyebrow}
          </p>
          <h2 className="mt-1 text-[15px] font-bold text-ink dark:text-fog">
            {ls.title}
          </h2>
          <p className={`mt-1 max-w-3xl text-[12px] leading-relaxed ${INK2}`}>
            {ls.sub}
          </p>
        </div>
        <span
          role="status"
          aria-live="polite"
          className={`shrink-0 pt-0.5 text-[11px] font-semibold ${
            status === "error" ? "text-coral" : status === "saved" ? "text-emerald-600" : INK2
          }`}
        >
          {status === "saving" && ls.saving}
          {status === "saved" && ls.saved}
          {status === "error" && (error ?? ls.saveErrorFallback)}
        </span>
      </header>

      <div className="space-y-5 px-5 py-5">
        <Group
          title={ls.cadenceTitle}
          note={ls.cadenceNote}
          help={
            <SettingHelp
              ariaLabel={ls.helpCadenceAria}
              title={ls.helpCadenceTitle}
              phrases={ls.cadence}
            />
          }
        >
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Num
              label={ls.nudge1}
              hint={ls.nudge1Hint}
              value={draft.first_nudge_minutes}
              min={5}
              max={60}
              suffix={ls.minSuffix}
              disabled={busy}
              onChange={set("first_nudge_minutes")}
            />
            <Num
              label={ls.nudge2}
              hint={ls.nudge2Hint}
              value={draft.second_followup_hours}
              min={2}
              max={168}
              suffix={ls.hourSuffix}
              disabled={busy}
              onChange={set("second_followup_hours")}
            />
            <Num
              label={ls.finalLabel}
              hint={ls.finalHint}
              value={draft.final_followup_hours}
              min={12}
              max={336}
              suffix={ls.hourSuffix}
              disabled={busy}
              onChange={set("final_followup_hours")}
            />
            <Num
              label={ls.capLabel}
              hint={ls.capHint}
              value={draft.max_attempts}
              min={0}
              max={4}
              suffix={ls.capSuffix}
              disabled={busy}
              onChange={set("max_attempts")}
            />
          </div>
        </Group>

        <Group
          title={ls.qualTitle}
          note={ls.qualNote}
        >
          <fieldset>
            <legend className="sr-only">{ls.qualLegend}</legend>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {LEAD_CATEGORIES.map((category) => {
                const checked = (draft.qualified_categories ?? []).includes(category);
                const isLastChecked =
                  checked && (draft.qualified_categories ?? []).length <= 1;
                return (
                  <label
                    key={category}
                    className={`flex cursor-pointer items-center gap-2 rounded-[2px] border ${HAIRLINE} bg-white px-3 py-2 text-[13px] font-medium ${INK} ${FOCUS}`}
                    title={
                      isLastChecked
                        ? ls.lastCheckedTitle
                        : undefined
                    }
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={busy || isLastChecked}
                      onChange={() => toggleQualifiedCategory(category)}
                      className="h-3.5 w-3.5 accent-[var(--ui-ink)]"
                    />
                    {leadCategoryLabelKnown(category, locale) ?? category}
                  </label>
                );
              })}
            </div>
          </fieldset>
        </Group>

        <Group
          title={ls.quietTitle}
          note={ls.quietNote}
          help={
            <SettingHelp
              ariaLabel={ls.helpQuietAria}
              title={ls.helpQuietTitle}
              phrases={ls.quiet}
            />
          }
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Num
              label={ls.quietStart}
              hint={ls.quietStartHint}
              value={draft.quiet_start_hour}
              min={0}
              max={23}
              suffix={ls.hourSuffix2}
              disabled={busy}
              onChange={set("quiet_start_hour")}
            />
            <Num
              label={ls.quietEnd}
              hint={ls.quietEndHint}
              value={draft.quiet_end_hour}
              min={0}
              max={23}
              suffix={ls.hourSuffix2}
              disabled={busy}
              onChange={set("quiet_end_hour")}
            />
            <label className="block">
              <span className={`block text-[12px] font-medium ${LABEL}`}>{ls.tzLabel}</span>
              <input
                type="text"
                list="sayvors-timezones"
                value={draft.timezone}
                disabled={busy}
                placeholder={ls.tzPh}
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
                {ls.tzHint}
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
                  {fill(ls.useDetected, { tz: browserTz })}
                </button>
              )}
            </label>
          </div>
        </Group>

        <Group
          title={ls.escTitle}
          note={ls.escNote}
          help={
            <SettingHelp
              ariaLabel={ls.helpEscAria}
              title={ls.helpEscTitle}
              phrases={ls.escalation}
            />
          }
        >
          <div className="grid gap-4 sm:grid-cols-3">
            <Num
              label={ls.escAfter}
              hint={ls.escAfterHint}
              value={draft.escalation_threshold}
              min={0}
              max={10}
              suffix={ls.cyclesSuffix}
              disabled={busy}
              onChange={set("escalation_threshold")}
            />
            <Num
              label={ls.resumeAfter}
              hint={ls.resumeHint}
              value={draft.escalation_resume_hours}
              min={1}
              max={336}
              suffix={ls.hourSuffix}
              disabled={busy}
              onChange={set("escalation_resume_hours")}
            />
            <Num
              label={ls.remindAfter}
              hint={ls.remindHint}
              value={draft.escalation_reminder_hours}
              min={1}
              max={72}
              suffix={ls.hourSuffix}
              disabled={busy}
              onChange={set("escalation_reminder_hours")}
            />
          </div>

          <div className="mt-4">
            <label className={`block text-[12px] font-medium ${LABEL}`}>
              {ls.recipients}
            </label>
            {memberLoadError ? (
              <p className="mt-1 text-[11px] text-ink/50 dark:text-fog/50">
                {ls.teamFallback}
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
                  {teamMembers.length === 0 ? ls.noMembers : ls.addPerson}
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
                {ls.add}
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
                placeholder={ls.manualPh}
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
                {ls.addAddress}
              </button>
            </div>

            {recipients.length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-1.5" aria-label={ls.recipientsAria}>
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
                      aria-label={fill(ls.removeRecipient, { email })}
                      className={`rounded-[1px] px-1 text-[13px] leading-none ${INK2} transition hover:text-coral disabled:opacity-40 ${FOCUS}`}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}

            <span className="mt-1 block text-[11px] text-ink/50 dark:text-fog/50">
              {ls.recipientsHint}
            </span>
          </div>
        </Group>

        <Group
          title={ls.digestTitle}
          note={ls.digestNote}
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
                {ls.digestLabel}
              </span>
              <span className={`block text-[11px] ${INK2}`}>
                {ls.digestHint}
              </span>
            </span>
          </label>

          {/* Disabled-until-enabled, so the two extra controls below never look
              like live settings while the digest is off. */}
          <div
            className={`mt-4 grid gap-4 sm:grid-cols-2 ${draft.digest_enabled ? "" : "opacity-50"}`}
          >
            <div>
              <span className={`block text-[12px] font-medium ${LABEL}`}>{ls.sendAt}</span>
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
                  aria-label={ls.amPmAria}
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
                {fill(ls.tzLine, { tz: draft.timezone })}
              </span>
            </div>

            <Num
              label={ls.howMany}
              hint={ls.howManyHint}
              value={draft.digest_max_leads}
              min={1}
              max={100}
              suffix={ls.leadsSuffix}
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
          {dirty ? ls.dirtyNote : ls.cleanNote}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={discard}
            disabled={!dirty || busy}
            className={`rounded-[2px] border ${HAIRLINE} bg-white px-3.5 py-2 text-[12px] font-bold ${INK} transition hover:bg-ink/[0.03] disabled:opacity-40 dark:bg-ink dark:hover:bg-fog/[0.06] ${FOCUS}`}
          >
            {ls.discard}
          </button>
          <button
            type="button"
            onClick={() => void save()}
            disabled={!dirty || busy}
            className={`rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40 ${FOCUS}`}
          >
            {status === "saving" ? ls.saving : ls.saveLead}
          </button>
        </div>
      </footer>
    </section>
  );
}