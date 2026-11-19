"use client";

/* Business-intake progress on the Knowledge Base page.
 *
 * Skipping the questionnaire in onboarding must never strand a tenant, so this
 * card is the permanent way back in. It answers three questions at a glance:
 * how complete is the profile, what is still missing, and where do I tap to
 * fix one specific answer. The checklist is capped so the card stays a nudge,
 * not a second questionnaire. The full answer list is opt-in and grouped by
 * the backend's sections so it reads as a table of contents, not a wall.
 */
import { Fragment, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api-rag";
import { useI18n } from "@/lib/i18n/I18nProvider";
import {
  intakeHref,
  isPending,
  remainingQuestions,
  sectionGroups,
  storedValues,
  type IntakeResponse,
} from "@/lib/business-intake";

/** A nudge, not a backlog: show the next few and a count for the rest. */
const CHECKLIST_LIMIT = 3;

const FOCUS =
  "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

export default function IntakeProgressCard() {
  const { t } = useI18n();
  const c = t.dashboard.businessIntake;
  const [intake, setIntake] = useState<IntakeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAnswers, setShowAnswers] = useState(false);

  useEffect(() => {
    let alive = true;
    apiFetch("/api/v1/profile/intake")
      .then((res) => {
        if (alive) setIntake(res as IntakeResponse);
      })
      .catch(() => {
        // The card is still useful without counts: the CTA below always works.
        if (alive) setIntake(null);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const questions = intake?.questions ?? [];
  const remaining = useMemo(() => remainingQuestions(questions), [questions]);
  const preview = remaining.slice(0, CHECKLIST_LIMIT);
  const groups = useMemo(
    () => sectionGroups(questions, (intake?.sections ?? []).map((s) => s.key)),
    [questions, intake],
  );

  const total = intake?.total ?? 0;
  const answered = intake?.answered ?? 0;
  const firstRemaining = remaining[0];
  const allDone = total > 0 && remaining.length === 0;

  const subtitle =
    !intake || total === 0
      ? c.subtitle
      : allDone
        ? c.allDone
        : remaining.length === 1
          ? c.remainingOne
          : fill(c.remainingMany, { n: remaining.length });

  const ctaHref = firstRemaining
    ? intakeHref(firstRemaining.section, firstRemaining.key)
    : intakeHref();
  const ctaLabel = firstRemaining
    ? preview.length === 1
      ? c.ctaAnswerOne
      : fill(c.ctaAnswerMore, { n: preview.length })
    : total > 0
      ? c.ctaEdit
      : c.ctaAnswer;

  return (
    <section
      aria-labelledby="intake-card-title"
      className="rounded-[32px] border border-card-border bg-card p-5 shadow-[0_18px_40px_-30px_rgba(20,16,31,0.45)] sm:p-6"
    >
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-[16px] bg-deep-violet/10 text-deep-violet">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              className="h-5 w-5"
              aria-hidden
            >
              <path d="M12 20h9" strokeLinecap="round" />
              <path
                d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4 12.5-12.5z"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <div className="min-w-0">
            <h2 id="intake-card-title" className="text-[15px] font-bold text-foreground">
              {c.title}
            </h2>
            <p className="mt-0.5 text-[12px] leading-relaxed text-foreground/55">
              {subtitle}
            </p>
          </div>
        </div>
        <Link
          href={ctaHref}
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-[24px] bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-sm transition hover:brightness-110 active:translate-y-[2px] active:scale-[0.98] ${FOCUS}`}
        >
          {ctaLabel}
          <span aria-hidden>→</span>
        </Link>
      </div>

      {total > 0 && (
        <div className="mt-4">
          <div
            className="h-2 overflow-hidden rounded-full bg-[var(--ui-sunken)]"
            role="progressbar"
            aria-valuenow={answered}
            aria-valuemin={0}
            aria-valuemax={total}
            aria-label={c.title}
          >
            <div
              className="h-full rounded-full bg-deep-violet transition-all duration-500"
              style={{ width: `${Math.min(100, (answered / total) * 100)}%` }}
            />
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <p className="text-[11px] font-semibold tabular-nums text-foreground/45">
              {fill(c.answered, { n: answered, total })}
            </p>
            {(intake?.skipped ?? 0) > 0 && (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700">
                {fill(c.skippedNote, { n: intake?.skipped ?? 0 })}
              </span>
            )}
            {questions.length > 0 && (
              <button
                type="button"
                onClick={() => setShowAnswers((v) => !v)}
                aria-expanded={showAnswers}
                aria-controls="intake-answers"
                className={`ms-auto text-[11px] font-bold text-deep-violet underline underline-offset-2 ${FOCUS}`}
              >
                {showAnswers ? c.hideAnswers : c.viewAnswers}
              </button>
            )}
          </div>
        </div>
      )}

      {preview.length > 0 && (
        <div className="mt-4 rounded-[20px] border border-card-border bg-[var(--ui-sunken)]/50 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-bold uppercase tracking-widest text-foreground/40">
              {c.stillToAnswer}
            </p>
            {remaining.length > preview.length && (
              <p className="text-[10px] font-semibold tabular-nums text-foreground/35">
                {fill(c.moreAfter, { n: remaining.length - preview.length })}
              </p>
            )}
          </div>
          <ul className="mt-2 space-y-1.5">
            {preview.map((q) => (
              <li key={q.key}>
                <Link
                  href={intakeHref(q.section, q.key)}
                  className={`group flex items-center gap-3 rounded-[14px] border border-card-border bg-card px-3 py-2 transition hover:border-deep-violet/40 hover:bg-white ${FOCUS}`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[12px] font-semibold text-foreground/85">
                      {q.label}
                    </span>
                    <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-foreground/40">
                      <span>{q.section_label}</span>
                      {q.skipped && (
                        <span className="rounded-full bg-amber-50 px-1.5 py-0.5 font-bold text-amber-700">
                          {c.skippedLabel}
                        </span>
                      )}
                    </span>
                  </span>
                  <span className="shrink-0 text-[11px] font-bold text-deep-violet group-hover:underline">
                    {c.answerCta}
                  </span>
                  <span aria-hidden className="shrink-0 text-deep-violet/50">
                    →
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {loading && total === 0 && (
        <div className="mt-4 space-y-2" aria-hidden>
          <div className="h-2 w-full animate-pulse rounded-full bg-foreground/[0.06]" />
          <div className="h-3 w-32 animate-pulse rounded-full bg-foreground/[0.04]" />
        </div>
      )}

      {showAnswers && questions.length > 0 && (
        <div
          id="intake-answers"
          className="mt-4 overflow-hidden rounded-[20px] border border-card-border"
        >
          <table className="w-full text-left text-[12px]">
            <caption className="sr-only">{c.viewAnswers}</caption>
            <thead className="bg-[var(--ui-sunken)] text-[10px] uppercase tracking-widest text-foreground/45">
              <tr>
                <th scope="col" className="px-3 py-2 font-bold">
                  {c.questionLabel}
                </th>
                <th scope="col" className="px-3 py-2 font-bold">
                  {c.yourAnswer}
                </th>
                <th scope="col" className="w-16 px-3 py-2 font-bold">
                  <span className="sr-only">{c.change}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => {
                const groupAnswered = group.questions.filter((q) => !isPending(q)).length;
                return (
                  <Fragment key={group.key}>
                    <tr className="border-t border-card-border bg-[var(--ui-sunken)]/60">
                      <th
                        scope="colgroup"
                        colSpan={3}
                        className="px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-foreground/45"
                      >
                        <span className="flex items-center justify-between gap-2">
                          <span>{group.label}</span>
                          <span className="tabular-nums text-foreground/35">
                            {fill(c.sectionCount, {
                              n: groupAnswered,
                              total: group.questions.length,
                            })}
                          </span>
                        </span>
                      </th>
                    </tr>
                    {group.questions.map((q) => {
                      const parts = q.skipped ? [] : storedValues(q.answer);
                      return (
                        <tr key={q.key} className="border-t border-card-border align-top">
                          <td className="px-3 py-2 font-medium text-foreground/70">{q.label}</td>
                          <td className="px-3 py-2">
                            {parts.length > 0 ? (
                              <span className="flex flex-wrap items-center gap-1.5">
                                {parts.map((part) => (
                                  <span
                                    key={part}
                                    className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[11px] font-semibold text-deep-violet"
                                  >
                                    {part}
                                  </span>
                                ))}
                                {q.answer_source === "google_confirmed" && (
                                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
                                    {c.fromGoogle}
                                  </span>
                                )}
                              </span>
                            ) : q.skipped ? (
                              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700">
                                {c.skippedLabel}
                              </span>
                            ) : (
                              <span className="text-foreground/35">{c.notAnswered}</span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-end">
                            <Link
                              href={intakeHref(q.section, q.key)}
                              className={`rounded-[10px] px-1.5 py-1 text-[11px] font-bold text-deep-violet underline underline-offset-2 ${FOCUS}`}
                            >
                              {c.change}
                            </Link>
                          </td>
                        </tr>
                      );
                    })}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
