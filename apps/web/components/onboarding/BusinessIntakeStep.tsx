"use client";

/* Business-intake cascade (onboarding step 2).
 *
 * The owner picks a vertical, then a sub-focus, then taps chips. Google's
 * already-known fields never appear as questions; `google_partial` ones are
 * pre-filled as one-tap confirmations. Nothing is typed unless a question
 * genuinely has no preset options.
 *
 * Style follows the onboarding shell: solid white surfaces, hairlines, no
 * gradients, no glass, 3px focus ring.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import { useI18n } from "@/lib/i18n/I18nProvider";
import {
  buildAnswersPayload,
  chipsFor,
  initialSelections,
  isAnswered,
  NOT_SURE,
  answeredCount,
  toggleChip,
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

export default function BusinessIntakeStep({ onComplete }: { onComplete: () => void }) {
  const { t } = useI18n();
  const c = t.dashboard.businessIntake;
  const [data, setData] = useState<IntakeResponse | null>(null);
  const [phase, setPhase] = useState<0 | 1 | 2>(0);
  const [vertical, setVertical] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [selections, setSelections] = useState<Selections>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const chosen = useMemo(
    () => data?.verticals.find((v) => v.key === vertical) ?? null,
    [data, vertical],
  );
  const focusOptions = chosen?.sub_focuses ?? [];
  const questions = data?.questions ?? [];
  const done = answeredCount(questions, selections);

  const chooseVertical = (key: string) => {
    setVertical(key);
    setFocus(null);
    setPhase(1);
    void load(key, null);
  };

  const chooseFocus = (key: string) => {
    setFocus(key);
    setPhase(2);
    void load(vertical, key);
  };

  const tapChip = (qKey: string, chip: string, multiple: boolean, googleValue: string | null) => {
    setSelections((prev) => {
      const current = prev[qKey] ?? { values: [], skipped: false, source: "manual" };
      if (chip === NOT_SURE) {
        return {
          ...prev,
          [qKey]: { values: [], skipped: !current.skipped, source: "manual" },
        };
      }
      const isGoogle = Boolean(googleValue && chip === googleValue);
      return {
        ...prev,
        [qKey]: {
          values: toggleChip(current.values, chip, multiple),
          skipped: false,
          source: isGoogle ? "google_confirmed" : "manual",
        },
      };
    });
  };

  const setFreeText = (qKey: string, value: string) => {
    setSelections((prev) => ({
      ...prev,
      [qKey]: { values: value ? [value] : [], skipped: false, source: "manual" },
    }));
  };

  const save = async () => {
    if (!vertical || saving) return;
    setSaving(true);
    setError(null);
    try {
      await apiFetch("/api/v1/profile/intake", {
        method: "PUT",
        body: JSON.stringify({
          vertical_key: vertical,
          sub_focus: focus,
          answers: buildAnswersPayload(questions, selections),
        }),
      });
      onComplete();
    } catch {
      setError(c.error);
    } finally {
      setSaving(false);
    }
  };

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
          {/* Google already knows the category — offer it instead of asking. */}
          {phase === 0 && data.google_suggestion && (
            <div className="rounded-[20px] border border-deep-violet/20 bg-deep-violet/[0.04] p-3">
              <p className="text-[12px] text-ink/70 dark:text-fog/70">
                {fill(c.googleSuggestion, { name: data.google_suggestion.vertical_label })}
              </p>
              <button
                type="button"
                onClick={() => chooseVertical(data.google_suggestion!.vertical_key)}
                className={`mt-2 rounded-[14px] bg-deep-violet px-3 py-1.5 text-[12px] font-bold text-white ${FOCUS}`}
              >
                {c.googleConfirm}
              </button>
            </div>
          )}

          {phase === 0 && (
            <div className="grid gap-2 sm:grid-cols-2">
              {data.verticals.map((v) => (
                <button
                  key={v.key}
                  type="button"
                  onClick={() => chooseVertical(v.key)}
                  className={`${CARD} ${FOCUS} text-left text-[13px] font-semibold text-ink transition hover:border-deep-violet/40 hover:bg-[#fbfaff] dark:text-fog`}
                >
                  {v.label}
                </button>
              ))}
            </div>
          )}

          {phase === 1 && (
            <div className="space-y-3">
              <p className="text-[13px] font-bold text-ink dark:text-fog">{c.pickFocus}</p>
              <div className="flex flex-wrap gap-2">
                {focusOptions.map((f) => (
                  <button
                    key={f.key}
                    type="button"
                    onClick={() => chooseFocus(f.key)}
                    className={`${CARD} ${FOCUS} rounded-[20px] px-4 py-2 text-[13px] font-semibold text-ink transition hover:border-deep-violet/40 dark:text-fog`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {phase === 2 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-[13px] font-bold text-ink dark:text-fog">{c.pickDetails}</p>
                <span className="text-[11px] tabular-nums text-ink/45">
                  {fill(c.answered, { n: done, total: questions.length })}
                </span>
              </div>

              {questions.map((q) => {
                const sel = selections[q.key];
                const chips = chipsFor(q);
                const answered = isAnswered(sel);
                return (
                  <div
                    key={q.key}
                    className={`${CARD} ${answered ? "border-deep-violet/30" : ""}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-[13px] font-semibold text-ink dark:text-fog">{q.label}</p>
                      {q.google_value && sel?.source === "google_confirmed" && (
                        <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-emerald-700">
                          {c.googleConfirmed}
                        </span>
                      )}
                    </div>
                    {q.google_value && (
                      <p className="mt-0.5 text-[11px] text-emerald-700 dark:text-emerald-400">
                        {fill(c.googleValue, { value: q.google_value })}
                      </p>
                    )}

                    {chips.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {chips.map((chip) => {
                          const active = Boolean(sel?.values.includes(chip));
                          const skipped = Boolean(sel?.skipped) && chip === NOT_SURE;
                          return (
                            <button
                              key={chip}
                              type="button"
                              aria-pressed={active || skipped}
                              onClick={() => tapChip(q.key, chip, q.multiple, q.google_value)}
                              className={`${FOCUS} rounded-full border px-3 py-1.5 text-[12px] font-medium transition ${
                                active || skipped
                                  ? "border-deep-violet bg-deep-violet text-white"
                                  : "border-ink/15 bg-white text-ink/70 hover:border-deep-violet/40 dark:text-fog/70"
                              }`}
                            >
                              {chip}
                            </button>
                          );
                        })}
                      </div>
                    ) : (
                      <input
                        type="text"
                        value={typeof sel?.values[0] === "string" ? sel.values[0] : ""}
                        onChange={(e) => setFreeText(q.key, e.target.value)}
                        placeholder={c.freeTextPlaceholder}
                        className={`${FOCUS} mt-3 w-full rounded-[20px] border border-ink/15 bg-white px-3 py-2 text-[13px] text-ink`}
                      />
                    )}
                    {sel?.skipped && (
                      <p className="mt-2 text-[10px] text-ink/40">{c.notSureHint}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <div className="flex items-center gap-3">
              {phase > 0 && (
                <button
                  type="button"
                  onClick={() => setPhase((p) => (p - 1) as 0 | 1 | 2)}
                  className={`${FOCUS} rounded-[14px] border border-ink/15 px-4 py-2 text-[12px] font-semibold text-ink/70 dark:text-fog/70`}
                >
                  {c.back}
                </button>
              )}
              <button type="button" onClick={onComplete} className={`${FOCUS} text-[12px] text-ink/40 underline underline-offset-2`}>
                {c.skip}
              </button>
            </div>
            {/* Picking a tile advances automatically, so there is no Next
                button to bypass the sub-focus choice. */}
            {phase === 2 && (
              <button
                type="button"
                onClick={() => void save()}
                disabled={saving || done === 0}
                className={`${FOCUS} rounded-[14px] bg-deep-violet px-5 py-2 text-[13px] font-bold text-white transition disabled:cursor-not-allowed disabled:opacity-40`}
              >
                {saving ? c.saving : c.save}
              </button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
