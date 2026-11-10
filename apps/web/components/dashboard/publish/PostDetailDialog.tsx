"use client";

import { useEffect, useState, type ReactNode } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import GoogleBusinessLogo from "@/components/channels/GoogleBusinessLogo";
import { apiFetch } from "@/lib/api-rag";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { checkWindow, minLocalInput, toLocalInput, type WindowError } from "@/lib/publish-schedule";
import { QUEUED_STATUSES, isRemovableJob, type PublishJob } from "@/lib/use-publish-jobs";
import { PLATFORM_META, type PlatformKey } from "./types";

/*
 * One post in detail, with the edits that can reach it.
 *
 * What can change depends on where the post is. Before it goes out, every field
 * can change. Once a Google post is live, its text, button and event window are
 * changed on Google, and its removal date moves. Anything else only shows its
 * details. The server applies the same rules, so a stale dialog cannot push a
 * change the platform would refuse.
 */

interface Draft {
  caption: string;
  description: string;
  ctaType: string;
  ctaUrl: string;
  startDate: string;
  endDate: string;
  scheduleAt: string;
  removeAt: string;
}

const API_FIELD: Record<keyof Draft, string> = {
  caption: "caption",
  description: "description",
  ctaType: "cta_type",
  ctaUrl: "cta_url",
  startDate: "start_date",
  endDate: "end_date",
  scheduleAt: "scheduled_at",
  removeAt: "delete_at",
};

const DATE_FIELDS = new Set<keyof Draft>(["startDate", "endDate", "scheduleAt", "removeAt"]);
const GOOGLE_TEXT_METHODS = new Set<string>(["update", "event", "offer"]);
const EVENT_METHODS = new Set<string>(["event", "offer"]);
const CTA_VALUES = ["book", "order", "shop", "learn_more", "sign_up", "call"] as const;
const FIELD =
  "rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]";

function editRights(job: PublishJob) {
  const queued = QUEUED_STATUSES.has(job.status);
  const live = job.status === "succeeded";
  const googleText = job.platform === "google_reviews" && GOOGLE_TEXT_METHODS.has(job.method ?? "");
  const text = queued || (live && googleText);
  return {
    text,
    event: EVENT_METHODS.has(job.method ?? "") && text,
    schedule: queued,
    removal: queued || live,
  };
}

function draftFrom(job: PublishJob): Draft {
  const local = (iso: string | null | undefined) => (iso ? toLocalInput(new Date(iso)) : "");
  return {
    caption: job.caption ?? "",
    description: job.description ?? "",
    ctaType: job.cta_type ?? "",
    ctaUrl: job.cta_url ?? "",
    startDate: local(job.start_date),
    endDate: local(job.end_date),
    scheduleAt: local(job.scheduled_at),
    removeAt: local(job.delete_at),
  };
}

function apiValue(field: keyof Draft, value: string): string | null {
  if (!value) return null;
  return DATE_FIELDS.has(field) ? new Date(value).toISOString() : value;
}

function formatWhen(iso: string | null | undefined, locale: string): string | null {
  return iso ? new Date(iso).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" }) : null;
}

export default function PostDetailDialog({
  job,
  destination,
  chip,
  onClose,
  onChanged,
  onRemove,
}: {
  job: PublishJob;
  destination: string;
  chip: { label: string; cls: string };
  onClose: () => void;
  onChanged: () => void;
  onRemove: (jobId: string) => void;
}) {
  const { t, locale } = useI18n();
  const d = t.publish.detail;
  const pc = t.publish.composer;
  const dates = t.publish.dates;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const rights = editRights(job);
  const editable = rights.text || rights.event || rights.schedule || rights.removal;
  const queued = QUEUED_STATUSES.has(job.status);
  const isEvent = EVENT_METHODS.has(job.method ?? "");
  const platform = job.platform as PlatformKey | null;
  const meta = platform ? PLATFORM_META[platform] : null;
  const methodLabel = job.method
    ? (t.publish.methods[job.method as keyof typeof t.publish.methods]?.label ?? job.method)
    : null;
  const googleLink = typeof job.result?.searchUrl === "string" ? job.result.searchUrl : null;
  const googlePost = job.platform === "google_reviews" && job.status === "succeeded";
  const removable = isRemovableJob(job);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(() => draftFrom(job));
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const startEdit = () => {
    setDraft(draftFrom(job));
    setError(null);
    setNotice(null);
    setEditing(true);
  };

  const windowMessage = (problem: WindowError) =>
    problem === "scheduleInPast"
      ? dates.scheduleInPast
      : problem === "removeBeforePublish"
        ? dates.removeBeforePublish
        : dates.eventEnd;

  const save = async () => {
    const initial = draftFrom(job);
    // Only the dates that changed are checked, so a queued post whose time has
    // already passed can still have its text fixed.
    const changed = (field: keyof Draft) => draft[field] !== initial[field];
    const problem = checkWindow({
      scheduleAt: rights.schedule && changed("scheduleAt") ? draft.scheduleAt : "",
      removeAt: rights.removal && changed("removeAt") ? draft.removeAt : "",
      startDate: rights.event && changed("startDate") ? draft.startDate : "",
      endDate: rights.event && changed("endDate") ? draft.endDate : "",
    });
    if (problem) {
      setError(windowMessage(problem));
      return;
    }
    const allowed: Record<keyof Draft, boolean> = {
      caption: rights.text,
      description: rights.text,
      ctaType: rights.text,
      ctaUrl: rights.text,
      startDate: rights.event,
      endDate: rights.event,
      scheduleAt: rights.schedule,
      removeAt: rights.removal,
    };
    const body: Record<string, string | null> = {};
    (Object.keys(allowed) as (keyof Draft)[]).forEach((field) => {
      if (allowed[field] && changed(field)) {
        body[API_FIELD[field]] = apiValue(field, draft[field]);
      }
    });
    if (Object.keys(body).length === 0) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await apiFetch(`/api/v1/channels/publish/${job.job_id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setEditing(false);
      setNotice(d.saved);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : d.saveFailed);
    } finally {
      setSaving(false);
    }
  };

  const checkGoogle = async () => {
    setChecking(true);
    setError(null);
    setNotice(null);
    try {
      await apiFetch(`/api/v1/channels/publish/${job.job_id}/refresh`, { method: "POST" });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : d.error);
    } finally {
      setChecking(false);
    }
  };

  const row = (label: string, value: ReactNode) => (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 text-[13px]">
      <dt className="text-ink/50 dark:text-fog/50">{label}</dt>
      <dd className="min-w-0 break-words text-ink dark:text-fog">{value}</dd>
    </div>
  );

  const field = (label: string, input: ReactNode) => (
    <label className="block text-[12px] font-semibold text-ink/60 dark:text-fog/60">
      {label}
      <span className="mt-1 block">{input}</span>
    </label>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4 py-6"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="post-detail-title"
        className="flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-[2px] bg-white shadow-2xl dark:bg-ink"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-ink/[0.06] px-5 py-4 dark:border-fog/[0.06]">
          <div className="flex min-w-0 items-center gap-2">
            {platform === "google_reviews" ? (
              <GoogleBusinessLogo size={16} />
            ) : platform ? (
              <PlatformMark platform={platform} size={16} />
            ) : null}
            <div className="min-w-0">
              <h2 id="post-detail-title" className="truncate text-[15px] font-bold text-ink dark:text-fog">
                {destination}
              </h2>
              <p className="mt-0.5 text-[12px] text-ink/50 dark:text-fog/50">
                {meta?.label ?? t.publish.unknownPlatform}
                {methodLabel ? ` · ${methodLabel}` : ""}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            autoFocus
            aria-label={d.close}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[2px] text-ink/45 transition hover:bg-ink/[0.04] hover:text-ink focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:text-fog/45"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden>
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {job.media_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- provider + storage hosts (no next.config allowlist)
            <img
              src={job.media_url}
              alt=""
              className="max-h-72 w-full rounded-[2px] bg-ink/[0.04] object-contain dark:bg-fog/[0.06]"
            />
          ) : (
            <p className="text-[12px] text-ink/45 dark:text-fog/45">{d.noImage}</p>
          )}

          <div className="flex flex-wrap items-center gap-1.5">
            <span className={`rounded-[2px] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${chip.cls}`}>
              {chip.label}
            </span>
          </div>

          {queued && <p className="text-[12px] text-ink/55 dark:text-fog/55">{d.queuedNote}</p>}
          {googlePost && editable && <p className="text-[12px] text-ink/55 dark:text-fog/55">{d.lockedNote}</p>}
          {!editable && <p className="text-[12px] text-ink/55 dark:text-fog/55">{d.notEditable}</p>}

          {editing ? (
            <form
              className="space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                void save();
              }}
            >
              {rights.text && (
                <>
                  {field(
                    d.caption,
                    <textarea
                      value={draft.caption}
                      onChange={(e) => setDraft({ ...draft, caption: e.target.value })}
                      rows={2}
                      maxLength={5000}
                      className={`${FIELD} w-full resize-y`}
                    />,
                  )}
                  {field(
                    d.description,
                    <textarea
                      value={draft.description}
                      onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                      rows={4}
                      maxLength={5000}
                      className={`${FIELD} w-full resize-y`}
                    />,
                  )}
                  <div className="grid gap-3 sm:grid-cols-2">
                    {field(
                      d.button,
                      <select
                        value={draft.ctaType}
                        onChange={(e) =>
                          setDraft({
                            ...draft,
                            ctaType: e.target.value,
                            ctaUrl: e.target.value === "call" ? "" : draft.ctaUrl,
                          })
                        }
                        className={`${FIELD} w-full`}
                      >
                        <option value="">{d.noButton}</option>
                        {CTA_VALUES.map((value) => (
                          <option key={value} value={value}>
                            {pc.ctaTypes[value]}
                          </option>
                        ))}
                      </select>,
                    )}
                    {draft.ctaType && draft.ctaType !== "call" &&
                      field(
                        d.buttonLink,
                        <input
                          type="url"
                          value={draft.ctaUrl}
                          onChange={(e) => setDraft({ ...draft, ctaUrl: e.target.value })}
                          placeholder={pc.ctaUrlPh}
                          className={`${FIELD} w-full`}
                        />,
                      )}
                  </div>
                </>
              )}

              {rights.event && (
                <div className="grid gap-3 sm:grid-cols-2">
                  {field(
                    d.eventStart,
                    <input
                      type="datetime-local"
                      min={minLocalInput()}
                      value={draft.startDate}
                      onChange={(e) => setDraft({ ...draft, startDate: e.target.value })}
                      className={`${FIELD} w-full`}
                    />,
                  )}
                  {field(
                    d.eventEnd,
                    <input
                      type="datetime-local"
                      min={minLocalInput()}
                      value={draft.endDate}
                      onChange={(e) => setDraft({ ...draft, endDate: e.target.value })}
                      className={`${FIELD} w-full`}
                    />,
                  )}
                </div>
              )}

              {rights.schedule &&
                field(
                  d.publishAt,
                  <input
                    type="datetime-local"
                    min={minLocalInput()}
                    value={draft.scheduleAt}
                    onChange={(e) => setDraft({ ...draft, scheduleAt: e.target.value })}
                    className={`${FIELD} w-full sm:w-64`}
                  />,
                )}

              {rights.removal &&
                field(
                  d.removeAt,
                  <input
                    type="datetime-local"
                    min={minLocalInput()}
                    value={draft.removeAt}
                    onChange={(e) => setDraft({ ...draft, removeAt: e.target.value })}
                    className={`${FIELD} w-full sm:w-64`}
                  />,
                )}
            </form>
          ) : (
            <dl className="divide-y divide-ink/[0.06] dark:divide-fog/[0.06]">
              {row(d.destination, destination)}
              {row(d.caption, job.caption || d.noText)}
              {job.description ? row(d.description, job.description) : null}
              {job.cta_type
                ? row(
                    d.button,
                    `${pc.ctaTypes[job.cta_type as keyof typeof pc.ctaTypes] ?? job.cta_type}${job.cta_url ? ` · ${job.cta_url}` : ""}`,
                  )
                : null}
              {isEvent && job.start_date ? row(d.eventStart, formatWhen(job.start_date, dateLocale)) : null}
              {isEvent && job.end_date ? row(d.eventEnd, formatWhen(job.end_date, dateLocale)) : null}
              {job.scheduled_at ? row(d.publishAt, formatWhen(job.scheduled_at, dateLocale)) : null}
              {job.delete_at ? row(d.removeAt, formatWhen(job.delete_at, dateLocale)) : null}
              {row(d.created, formatWhen(job.created_at, dateLocale))}
              {job.last_error ? (
                row(d.error, <span className="text-red-600 dark:text-red-400">{job.last_error}</span>)
              ) : null}
              {typeof job.result?.delete_error === "string" ? (
                row(
                  d.error,
                  <span className="text-red-600 dark:text-red-400">{job.result.delete_error}</span>,
                )
              ) : null}
              {googleLink
                ? row(
                    d.viewOnGoogle,
                    <a
                      href={googleLink}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-semibold text-deep-violet underline underline-offset-2"
                    >
                      {d.viewOnGoogle}
                    </a>,
                  )
                : null}
            </dl>
          )}

          {notice && (
            <p role="status" className="text-[12px] font-semibold text-emerald-700 dark:text-emerald-400">
              {notice}
            </p>
          )}
          {error && (
            <p role="alert" className="text-[12px] font-semibold text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-ink/[0.06] px-5 py-3 dark:border-fog/[0.06]">
          {editing ? (
            <>
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving}
                className="rounded-[2px] bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40"
              >
                {saving ? d.saving : d.save}
              </button>
              <button
                type="button"
                onClick={() => {
                  setEditing(false);
                  setError(null);
                }}
                disabled={saving}
                className="rounded-[2px] border border-ink/[0.1] px-4 py-2 text-[13px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] disabled:opacity-50 dark:border-fog/[0.12] dark:text-fog/60"
              >
                {d.discard}
              </button>
            </>
          ) : (
            <>
              {editable && (
                <button
                  type="button"
                  onClick={startEdit}
                  className="rounded-[2px] bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40"
                >
                  {d.edit}
                </button>
              )}
              {googlePost && (
                <button
                  type="button"
                  onClick={() => void checkGoogle()}
                  disabled={checking}
                  className="rounded-[2px] border border-ink/[0.1] px-4 py-2 text-[13px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] disabled:opacity-50 dark:border-fog/[0.12] dark:text-fog/60"
                >
                  {checking ? d.checking : d.checkGoogle}
                </button>
              )}
              {removable && (
                <button
                  type="button"
                  onClick={() => onRemove(job.job_id)}
                  className="ms-auto rounded-[2px] border border-red-500/40 px-4 py-2 text-[13px] font-semibold text-red-700 transition hover:bg-red-500/10 dark:text-red-400"
                >
                  {queued ? t.publish.cancel : d.removeNow}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
