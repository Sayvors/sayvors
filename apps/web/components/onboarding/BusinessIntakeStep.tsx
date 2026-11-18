"use client";

/* Business-intake cascade, onboarding + dashboard (one shared component).
 *
 * Phase 0: pick a vertical. Phase 1: pick a sub-focus. Phase 2: answer one
 * question at a time. Google already knows hours, address and attributes —
 * those fields are never asked; a `google_partial` value is offered as a
 * one-tap confirmation instead. "Not sure" is a decline recorded as unknown,
 * never as a fact. Answers are drafted to the API as the owner goes, so
 * leaving halfway does not lose work.
 *
 * Style follows the onboarding shell: solid white surfaces, hairlines, no
 * gradients, no glass, 3px focus ring.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { useI18n } from "@/lib/i18n/I18nProvider";
import IntakeChoiceGrid from "./IntakeChoiceGrid";
import {
  buildAnswersPayload,
  initialSelections,
  isAnswered,
  NOT_SURE,
  optionChoices,
  answeredCount,
  toggleChip,
  type IntakeChoice,
  type IntakeQuestion,
  type IntakeResponse,
  type Selections,
} from "@/lib/business-intake";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

const CARD =
  "rounded-[24px] border border-ink/[0.08] bg-white p-4 shadow-[0_12px_28px_-24px_rgba(20,16,31,0.5)]";
const FOCUS =
  "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet";
const DRAFT_DELAY_MS = 900;

type Phase = 0 | 1 | 2;
type SaveState = "idle" | "saving" | "saved" | "error";

export default function BusinessIntakeStep({
  onComplete,
  skipLabel,
}: {
  onComplete: () => void;
  /** Dashboard embedding uses "Cancel"; onboarding uses "Skip for now". */
  skipLabel?: string;
}) {
  const { t } = useI18n();
  const c = t.dashboard.businessIntake;
  const [data, setData] = useState<IntakeResponse | null>(null);
  const [phase, setPhase] = useState<Phase>(0);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [vertical, setVertical] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [selections, setSelections] = useState<Selections>({});
  const [googleDismissed, setGoogleDismissed] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);
  const draftTimer = useRef<number | null>(null);
  const savingRef = useRef(false);

  const load = useCallback(async (v: string | null, f: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (v) params.set("vertical_key", v);
      if (f) params.set("sub_focus", f);
      const suffix = params.toString() ? `?${params}` : "";
      const res: IntakeResponse = await apiFetch(`/api/v1/profile/intake${suffix}`);
      setData(res);
      setSelections((prev) => {
        const next = initialSelections(res.questions);
        for (const key of Object.keys(next)) {
          if (prev[key]) next[key] = prev[key];
        }
        return next;
      });
      if (!v && res.vertical_key) setVertical(res.vertical_key);
      if (!f && res.sub_focus) setFocus(res.sub_focus);
    } catch {
      setError(c.error);
    } finally {
      setLoading(false);
    }
  }, [c.error]);

  useEffect(() => {
    void load(null, null);
  }, [load]);

  useEffect(() => () => {
    if (draftTimer.current) window.clearTimeout(draftTimer.current);
  }, []);

  const chosen = useMemo(
    () => data?.verticals.find((v) => v.key === vertical) ?? null,
    [data, vertical],
  );
  const focusOptions = chosen?.sub_focuses ?? [];
  const chosenFocus = focusOptions.find((f) => f.key === focus) ?? null;
  const questions = data?.questions ?? [];
  const question: IntakeQuestion | undefined = questions[questionIndex];
  const done = answeredCount(questions, selections);

  const persist = useCallback(async (finish: boolean): Promise<boolean> => {
    // Ref guard, not the `saving` state: using the state here would change this
    // callback's identity when a save finishes and re-arm the draft timer,
    // creating an endless save loop.
    if (!vertical || !data || savingRef.current) return false;
    savingRef.current = true;
    setSaving(true);
    setSaveState("saving");
    setError(null);
    try {
      await apiFetch("/api/v1/profile/intake", {
        method: "PUT",
        body: JSON.stringify({
          vertical_key: vertical,
          sub_focus: focus,
          answers: buildAnswersPayload(data.questions, selections),
        }),
      });
      setSaveState("saved");
      if (finish) onComplete();
      return true;
    } catch {
      setSaveState("error");
      setError(c.error);
      return false;
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [vertical, focus, data, selections, onComplete, c.error]);

  // Draft autosave. Runs only after the initial load settles, so a tenant who
  // taps three cards and closes the tab still finds their answers later.
  useEffect(() => {
    if (loading || !data || !vertical) return;
    if (draftTimer.current) window.clearTimeout(draftTimer.current);
    draftTimer.current = window.setTimeout(() => {
      void persist(false);
    }, DRAFT_DELAY_MS);
    return () => {
      if (draftTimer.current) window.clearTimeout(draftTimer.current);
    };
  }, [loading, data, vertical, persist]);

  const selectVertical = (key: string) => {
    setVertical(key);
    setFocus(null);
    setQuestionIndex(0);
    void load(key, null);
  };

  const selectFocus = (key: string) => {
    setFocus(key);
    setQuestionIndex(0);
    void load(vertical, key);
  };

  const tapChoice = (q: IntakeQuestion, value: string) => {
    if (value === NOT_SURE) {
      setSelections((prev) => {
        const current = prev[q.key] ?? { values: [], skipped: false, source: "manual" };
        return {
          ...prev,
          [q.key]: { values: [], skipped: !current.skipped, source: "manual" },
        };
      });
      return;
    }
    setSelections((prev) => {
      const current = prev[q.key] ?? { values: [], skipped: false, source: "manual" };
      const isGoogle = Boolean(q.google_value && value === q.google_value);
      return {
        ...prev,
        [q.key]: {
          values: toggleChip(current.values, value, q.multiple),
          skipped: false,
          source: isGoogle ? "google_confirmed" : "manual",
        },
      };
    });
  };

  const confirmGoogle = (q: IntakeQuestion) => {
    if (!q.google_value) return;
    setSelections((prev) => ({
      ...prev,
      [q.key]: {
        values: [q.google_value as string],
        skipped: false,
        source: "google_confirmed",
      },
    }));
  };

  const setFreeText = (q: IntakeQuestion, value: string) => {
    setSelections((prev) => ({
      ...prev,
      [q.key]: { values: value ? [value] : [], skipped: false, source: "manual" },
    }));
  };

  const goBack = () => {
    if (phase === 2 && questionIndex > 0) {
      setQuestionIndex((i) => i - 1);
    } else if (phase === 2) {
      setPhase(1);
    } else if (phase === 1) {
      setPhase(0);
    }
  };

  const goNext = () => {
    if (phase === 0 && vertical) {
      setPhase(1);
    } else if (phase === 1 && focus) {
      setPhase(2);
      setQuestionIndex(0);
    } else if (phase === 2) {
      if (questionIndex < questions.length - 1) {
        setQuestionIndex((i) => i + 1);
      } else {
        void persist(true);
      }
    }
  };

  const selection = question ? selections[question.key] : undefined;
  const choices: IntakeChoice[] = question
    ? optionChoices(question).map((option) => ({
        key: option.value,
        title: option.value,
        description: option.notSure
          ? c.notSureCard
          : option.google
            ? c.googleOptionHint
            : c.tapToSelect,
        badge: option.google ? c.fromGoogle : undefined,
        tone: option.notSure ? "notSure" : "default",
      }))
    : [];
  const canAdvance =
    (phase === 0 && Boolean(vertical)) ||
    (phase === 1 && Boolean(focus)) ||
    phase === 2;

  return (
    <section className="space-y-4">
      <div className="text-center">
        <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-deep-violet/70">
          {fill(c.stepOf, { n: phase + 1 })}
        </p>
        <h2 className="mt-1 text-[20px] font-bold text-ink dark:text-fog">{c.title}</h2>
        <p className="mt-1 text-[13px] text-ink/50 dark:text-fog/50">{c.subtitle}</p>
      </div>

      {error && (
        <p role="alert" className="rounded-[16px] border border-red-300 bg-red-50 px-3 py-2 text-[12px] text-red-700">
          {error}
        </p>
      )}

      {loading && <p className="py-6 text-center text-[13px] text-ink/40">…</p>}

      {!loading && data && (
        <>
          {/* Chosen path stays visible, so a tenant never wonders where the
              questions came from. Either crumb can be changed in one tap. */}
          {(vertical || focus) && (
            <div className="flex flex-wrap items-center gap-2 rounded-[16px] border border-ink/[0.08] bg-white px-3 py-2 dark:bg-[#241a45]">
              <span className="text-[11px] font-semibold text-ink/45 dark:text-fog/45">
                {c.yourBusiness}
              </span>
              <button
                type="button"
                onClick={() => { setPhase(0); setQuestionIndex(0); }}
                className={`${FOCUS} rounded-full px-2 py-1 text-[12px] font-bold text-ink underline decoration-ink/20 underline-offset-2 dark:text-fog`}
              >
                {chosen?.label ?? c.changeVertical}
                <span className="ms-1.5 text-[10px] font-semibold text-deep-violet/70">{c.change}</span>
              </button>
              {focus && (
                <>
                  <span aria-hidden className="text-[11px] text-ink/30">›</span>
                  <button
                    type="button"
                    onClick={() => { setPhase(1); setQuestionIndex(0); }}
                    className={`${FOCUS} rounded-full px-2 py-1 text-[12px] font-bold text-ink underline decoration-ink/20 underline-offset-2 dark:text-fog`}
                  >
                    {chosenFocus?.label ?? c.changeFocus}
                    <span className="ms-1.5 text-[10px] font-semibold text-deep-violet/70">{c.change}</span>
                  </button>
                </>
              )}
            </div>
          )}

          {phase === 0 && (
            <div className="space-y-3">
              <p className="text-[13px] font-bold text-ink dark:text-fog">{c.pickVertical}</p>
              {data.google_suggestion && (
                <div className="rounded-[20px] border border-deep-violet/20 bg-deep-violet/[0.04] p-3">
                  <p className="text-[12px] text-ink/70 dark:text-fog/70">
                    {fill(c.googleSuggestion, { name: data.google_suggestion.vertical_label })}
                  </p>
                  <button
                    type="button"
                    onClick={() => selectVertical(data.google_suggestion!.vertical_key)}
                    className={`mt-2 rounded-[14px] bg-deep-violet px-3 py-1.5 text-[12px] font-bold text-white transition hover:brightness-110 ${FOCUS}`}
                  >
                    {c.googleConfirm}
                  </button>
                </div>
              )}
              <IntakeChoiceGrid
                label={c.pickVertical}
                choices={data.verticals.map((v) => ({
                  key: v.key,
                  title: v.label,
                  description: fill(c.verticalHint, { n: v.sub_focuses.length }),
                }))}
                selected={vertical ? [vertical] : []}
                onChoose={selectVertical}
                columns="three"
              />
            </div>
          )}

          {phase === 1 && (
            <div className="space-y-3">
              <p className="text-[13px] font-bold text-ink dark:text-fog">{c.pickFocus}</p>
              <IntakeChoiceGrid
                label={c.pickFocus}
                choices={focusOptions.map((f) => ({
                  key: f.key,
                  title: f.label,
                  description: c.focusHint,
                }))}
                selected={focus ? [focus] : []}
                onChoose={selectFocus}
              />
            </div>
          )}

          {phase === 2 && question && (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[13px] font-bold text-ink dark:text-fog">{question.label}</p>
                <span className="shrink-0 text-[11px] tabular-nums text-ink/45">
                  {fill(c.questionOf, { n: questionIndex + 1, total: questions.length })}
                </span>
              </div>
              <div
                className="h-1.5 overflow-hidden rounded-full bg-[var(--ui-sunken)]"
                role="progressbar"
                aria-valuenow={done}
                aria-valuemin={0}
                aria-valuemax={questions.length}
                aria-label={c.pickDetails}
              >
                <div
                  className="h-full rounded-full bg-deep-violet transition-[width] duration-300"
                  style={{ width: `${questions.length ? (done / questions.length) * 100 : 0}%` }}
                />
              </div>
              <p className="text-[11px] tabular-nums text-ink/45">
                {fill(c.answered, { n: done, total: questions.length })}
              </p>

              {question.google_value &&
                selection?.source !== "google_confirmed" &&
                !googleDismissed[question.key] && (
                  <div className="rounded-[20px] border border-deep-violet/20 bg-deep-violet/[0.04] p-4">
                    <p className="text-[13px] font-bold text-ink dark:text-fog">
                      {fill(c.googleAsk, { value: question.google_value })}
                    </p>
                    <p className="mt-1 text-[11px] text-ink/50 dark:text-fog/50">{c.googleConfirmHint}</p>
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      <button
                        type="button"
                        onClick={() => confirmGoogle(question)}
                        className={`${FOCUS} rounded-[14px] bg-deep-violet px-3 py-2 text-[12px] font-bold text-white transition hover:brightness-110`}
                      >
                        {c.googleUse}
                      </button>
                      <button
                        type="button"
                        onClick={() => setGoogleDismissed((prev) => ({ ...prev, [question.key]: true }))}
                        className={`${FOCUS} rounded-[14px] border border-ink/15 bg-white px-3 py-2 text-[12px] font-bold text-ink/70 transition hover:border-deep-violet/40 dark:bg-[#241a45] dark:text-fog/70`}
                      >
                        {c.googleDifferent}
                      </button>
                    </div>
                  </div>
                )}

              {selection?.source === "google_confirmed" && question.google_value && (
                <p className="rounded-[16px] bg-emerald-50 px-3 py-2 text-[11px] font-semibold text-emerald-700">
                  {fill(c.googleValue, { value: question.google_value })} · {c.googleConfirmed}
                </p>
              )}

              {choices.length > 0 ? (
                <IntakeChoiceGrid
                  label={question.label}
                  choices={choices}
                  multiple={question.multiple}
                  selected={selection?.skipped ? [NOT_SURE] : (selection?.values ?? [])}
                  onChoose={(value) => tapChoice(question, value)}
                  columns="two"
                />
              ) : (
                <div className={CARD}>
                  <label htmlFor={`intake-${question.key}`} className="text-[13px] font-semibold text-ink dark:text-fog">
                    {c.freeTextLabel}
                  </label>
                  <input
                    id={`intake-${question.key}`}
                    type="text"
                    value={typeof selection?.values[0] === "string" ? selection.values[0] : ""}
                    onChange={(e) => setFreeText(question, e.target.value)}
                    placeholder={c.freeTextPlaceholder}
                    className={`${FOCUS} mt-2 w-full rounded-[20px] border border-ink/15 bg-white px-3 py-2 text-[13px] text-ink dark:bg-[#241a45] dark:text-fog`}
                  />
                </div>
              )}

              {selection?.skipped && (
                <p role="status" className="rounded-[16px] bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
                  {c.notSureHint}
                </p>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <div className="flex flex-wrap items-center gap-3">
              {(phase > 0 || questionIndex > 0) && (
                <button
                  type="button"
                  onClick={goBack}
                  className={`${FOCUS} rounded-[14px] border border-ink/15 px-4 py-2 text-[12px] font-semibold text-ink/70 transition hover:border-deep-violet/40 dark:text-fog/70`}
                >
                  {c.back}
                </button>
              )}
              <button type="button" onClick={onComplete} className={`${FOCUS} text-[12px] text-ink/40 underline underline-offset-2`}>
                {skipLabel ?? c.skip}
              </button>
              <span aria-live="polite" className="text-[11px] text-ink/40">
                {saveState === "saving"
                  ? c.savingDraft
                  : saveState === "saved"
                    ? c.savedNow
                    : saveState === "error"
                      ? c.error
                      : ""}
              </span>
            </div>
            <button
              type="button"
              onClick={goNext}
              disabled={!canAdvance || saving}
              className={`${FOCUS} rounded-[14px] bg-deep-violet px-5 py-2 text-[13px] font-bold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40`}
            >
              {phase === 2 && questionIndex === questions.length - 1
                ? c.finish
                : c.next}
            </button>
          </div>
        </>
      )}
    </section>
  );
}
