"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import LogoLoader from "@/components/LogoLoader";
import { useI18n } from "@/lib/i18n/I18nProvider";
import {
  approveGoogleAnswer,
  draftGoogleAnswer,
  editGoogleAnswerDraft,
  fetchGoogleQuestions,
  ignoreGoogleQuestion,
  rejectGoogleAnswerDraft,
  type GoogleQuestion,
} from "@/lib/api-qa";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

const MAX_VISIBLE = 5;
const QA_QUERY_KEY = ["google-qa"] as const;
// Google discontinued the My Business Q&A API on 2025-11-03. Existing
// questions stay readable, but the write actions can never succeed again.
const QA_RETIRED = true;

function initial(name: string | null): string {
  return (name || "?").trim().charAt(0).toUpperCase() || "?";
}

/**
 * Google listing Q&A. The card is intentionally an action surface: an
 * unanswered public question costs conversions, so answer generation and
 * approval live here rather than behind a second settings page.
 */
export default function GoogleQuestionsCard() {
  const { t, locale } = useI18n();
  const qa = t.reviews.qa;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: QA_QUERY_KEY,
    queryFn: () => fetchGoogleQuestions({ limit: 50 }),
    staleTime: 30 * 1000,
  });
  const [actionError, setActionError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTexts, setDraftTexts] = useState<Record<string, string>>({});

  const questions = query.data?.items ?? [];
  const unanswered = query.data?.unanswered_count ?? 0;

  const run = async (id: string, action: () => Promise<GoogleQuestion>) => {
    setBusyId(id);
    setActionError(null);
    try {
      const updated = await action();
      setDraftTexts((prev) => ({ ...prev, [id]: updated.draft_answer_text ?? "" }));
      await queryClient.invalidateQueries({ queryKey: QA_QUERY_KEY });
    } catch {
      setActionError(qa.actionFailed);
    } finally {
      setBusyId(null);
    }
  };

  const visible = (showAll ? questions : questions.slice(0, MAX_VISIBLE)).filter(
    (q) => !q.is_ignored || showAll,
  );
  const hidden = Math.max(
    0,
    questions.filter((q) => !q.is_ignored).length - MAX_VISIBLE,
  );
  const error = actionError || (query.isError
    ? qa.loadFailed
    : null);

  return (
    <section className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">{qa.title}</h2>
            {unanswered > 0 && (
              <span className="rounded-full bg-coral/10 px-2 py-0.5 text-[10px] font-bold text-coral">
                {fill(qa.toAnswer, { n: fmt(unanswered) })}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">
            {qa.sub}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
          className="rounded-lg border border-ink/[0.08] px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:text-ink disabled:opacity-50 dark:border-fog/[0.1] dark:text-fog/60 dark:hover:text-fog"
        >
          {qa.refresh}
        </button>
      </div>

      {QA_RETIRED && (
        <p className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] font-medium text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
          {qa.retiredNote}
        </p>
      )}

      {error && (
        <p role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-[11px] font-medium text-red-700 dark:border-red-900/50 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </p>
      )}

      {query.isLoading ? (
        <div className="flex justify-center py-8">
          <LogoLoader size={24} />
        </div>
      ) : visible.length === 0 ? (
        <p className="py-6 text-center text-[12px] text-ink/40 dark:text-fog/40">
          {qa.empty}
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-ink/[0.05] dark:divide-fog/[0.06]">
          {visible.map((q) => {
            const draft = draftTexts[q.id] ?? q.draft_answer_text ?? "";
            const isEditing = editingId === q.id;
            const busy = busyId === q.id;
            return (
              <li key={q.id} className="py-3 first:pt-1">
                <div className="flex items-start gap-3">
                  <span
                    aria-hidden
                    className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-deep-violet/10 text-[11px] font-bold text-deep-violet"
                  >
                    {initial(q.asker_name)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[12.5px] font-medium text-ink dark:text-fog">{q.question_text}</p>
                    <p className="mt-0.5 text-[10.5px] text-ink/40 dark:text-fog/40">
                      {q.asker_name || qa.customerFallback}
                      {q.question_created_at
                        ? ` · ${new Date(q.question_created_at).toLocaleDateString(dateLocale)}`
                        : ""}
                      {q.upvote_count > 0 ? ` · ${fill(qa.upvotes, { n: fmt(q.upvote_count) })}` : ""}
                    </p>

                    {q.is_answered && q.answer_text ? (
                      <p className="mt-2 rounded-xl bg-emerald-50 px-3 py-2 text-[11.5px] text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300">
                        {q.answer_text}
                      </p>
                    ) : isEditing || q.draft_status === "pending_approval" ? (
                      <div className="mt-2">
                        <textarea
                          value={draft}
                          onChange={(e) =>
                            setDraftTexts((prev) => ({ ...prev, [q.id]: e.target.value }))
                          }
                          rows={2}
                          aria-label={qa.draftAria}
                          className="input-field w-full resize-y text-[12px]"
                          placeholder={qa.draftPh}
                        />
                        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                          <button
                            type="button"
                            disabled={QA_RETIRED || busy || !draft.trim()}
                            onClick={() =>
                              void run(q.id, async () => {
                                await editGoogleAnswerDraft(q.id, draft.trim());
                                return approveGoogleAnswer(q.id);
                              })
                            }
                            className="rounded-lg bg-deep-violet px-2.5 py-1.5 text-[11px] font-bold text-white disabled:opacity-50"
                          >
                            {busy ? qa.posting : qa.approvePost}
                          </button>
                          <button
                            type="button"
                            disabled={QA_RETIRED || busy}
                            onClick={() =>
                              void run(q.id, () =>
                                q.draft_status === "pending_approval"
                                  ? editGoogleAnswerDraft(q.id, draft.trim())
                                  : draftGoogleAnswer(q.id, draft.trim()),
                              )
                            }
                            className="rounded-lg border border-ink/[0.08] px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 disabled:opacity-50 dark:border-fog/[0.1] dark:text-fog/60"
                          >
                            {qa.saveDraft}
                          </button>
                          <button
                            type="button"
                            disabled={QA_RETIRED || busy}
                            onClick={() =>
                              void run(q.id, () => rejectGoogleAnswerDraft(q.id)).then(() => {
                                setDraftTexts((prev) => ({ ...prev, [q.id]: "" }));
                                setEditingId(null);
                              })
                            }
                            className="rounded-lg px-2 py-1.5 text-[11px] font-semibold text-ink/40 hover:text-ink dark:text-fog/40 dark:hover:text-fog"
                          >
                            {qa.discard}
                          </button>
                        </div>
                        {q.draft_error && (
                          <p role="alert" className="mt-1.5 text-[11px] text-red-600">
                            {q.draft_error}
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="mt-2 flex flex-wrap items-center gap-1.5">
                        <button
                          type="button"
                          disabled={QA_RETIRED || busy}
                          onClick={() =>
                            void run(q.id, async () => {
                              const generated = await draftGoogleAnswer(q.id);
                              setDraftTexts((prev) => ({
                                ...prev,
                                [q.id]: generated.draft_answer_text ?? "",
                              }));
                              setEditingId(q.id);
                              return generated;
                            })
                          }
                          className="rounded-lg bg-deep-violet px-2.5 py-1.5 text-[11px] font-bold text-white disabled:opacity-50"
                        >
                          {busy ? qa.drafting : qa.draftAi}
                        </button>
                        <button
                          type="button"
                          disabled={QA_RETIRED || busy}
                          onClick={() => setEditingId(q.id)}
                          className="rounded-lg border border-ink/[0.08] px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 dark:border-fog/[0.1] dark:text-fog/60"
                        >
                          {qa.writeAnswer}
                        </button>
                        <button
                          type="button"
                          disabled={QA_RETIRED || busy}
                          onClick={() => void run(q.id, () => ignoreGoogleQuestion(q.id))}
                          className="rounded-lg px-2 py-1.5 text-[11px] font-semibold text-ink/35 hover:text-ink dark:text-fog/35 dark:hover:text-fog"
                        >
                          {qa.ignore}
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-2 text-[11px] font-semibold text-deep-violet hover:underline"
        >
          {showAll ? qa.showFewer : hidden === 1 ? qa.showMoreOne : fill(qa.showMoreN, { n: fmt(hidden) })}
        </button>
      )}
    </section>
  );
}
