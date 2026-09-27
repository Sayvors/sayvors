"use client";

import { useState } from "react";
import { ReviewInsight, correctReviewMeaning } from "@/lib/api-analytics";
import { MEANING_SUBJECTS, subjectLabel } from "@/lib/meaning";

/**
 * Meaning inspector: what did the AI understand this review to mean, and the
 * controls to correct it.
 *
 * This exists because the AI once read the Arabic review "you need to fix
 * your building" as "bank account corrections" and the report turned that into
 * a HIGH-priority opportunity and a business action. Nothing caught it, because
 * the report verified its *counts* and never its *meaning*.
 *
 * Two things make a reading checkable here:
 *   - the subject is a fixed vocabulary, not free text
 *   - the evidence spans are verbatim from the review, shown as-is
 *
 * A correction is saved as `source: "human"` and is never overwritten by a
 * later re-analysis, so this is a real decision and not a suggestion.
 */
export default function MeaningInspector({
  review,
  onSaved,
  onError,
}: {
  review: ReviewInsight;
  onSaved: (updated: ReviewInsight) => void;
  onError: (message: string) => void;
}) {
  const meaning = review.meaning ?? null;
  const [open, setOpen] = useState(false);
  const [subject, setSubject] = useState(meaning?.subject ?? "other");
  const [problem, setProblem] = useState(meaning?.problem ?? "");
  const [saving, setSaving] = useState(false);

  const startEditing = () => {
    setSubject(meaning?.subject ?? "other");
    setProblem(meaning?.problem ?? "");
    setOpen(true);
  };

  const save = async () => {
    setSaving(true);
    try {
      const updated = await correctReviewMeaning(review.id, {
        subject,
        problem: problem.trim() || null,
        needs_human: false,
      });
      onSaved(updated);
      setOpen(false);
    } catch (e) {
      const detail =
        e && typeof e === "object" && "detail" in e
          ? String((e as { detail?: unknown }).detail)
          : "";
      onError(detail || "Could not save the correction.");
    } finally {
      setSaving(false);
    }
  };

  if (!meaning) {
    return (
      <div className="rounded-lg border border-dashed border-[#DADCE0] bg-[#F8F9FA] px-4 py-3">
        <p className="text-[12px] font-medium text-[#5F6368]">Meaning not analysed yet</p>
        <p className="mt-1 text-[11px] leading-4 text-[#5F6368]/80">
          The AI has not worked out what this review is about. It will be picked up
          on the next sync. Until then it is excluded from themes, so nothing is
          invented about it.
        </p>
      </div>
    );
  }

  const needsHuman = meaning.needs_human === true;
  const corrected = meaning.source === "human";
  const evidence = meaning.evidence ?? [];

  return (
    <div
      className={`rounded-lg border px-4 py-3 ${
        corrected
          ? "border-[#CEEAD6] bg-[#E6F4EA]"
          : needsHuman
            ? "border-[#F4B400]/40 bg-[#FEF7E0]"
            : "border-[#E8EAED] bg-[#F8F9FA]"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[13px] font-semibold text-[#202124]">What this review means</p>
        {corrected ? (
          <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#137333]">
            Corrected by you
          </span>
        ) : (
          <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#5F6368]">
            {meaning.source === "heuristic" ? "Keyword guess" : "AI reading"}
          </span>
        )}
        {meaning.negated && (
          <span
            title="The customer denies something here (e.g. “no problems”). Not a complaint."
            className="rounded-full bg-[#E8F0FE] px-2 py-0.5 text-[10px] font-bold text-[#1967D2]"
          >
            Negated
          </span>
        )}
        <span className="flex-1" />
        {!open && (
          <button
            onClick={startEditing}
            className="rounded-md border border-[#DADCE0] bg-white px-2.5 py-1 text-[11px] font-medium text-[#1A73E8] transition hover:bg-[#E8F0FE]"
          >
            {corrected ? "Edit" : "Correct this"}
          </button>
        )}
      </div>

      {!open && (
        <div className="mt-2.5 space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-[12px]">
            <span className="text-[#5F6368]">Subject</span>
            <span className="rounded-full bg-[#E8F0FE] px-2 py-0.5 font-medium text-[#1967D2]">
              {subjectLabel(meaning.subject)}
            </span>
            {meaning.intent && <span className="text-[#5F6368]">· {meaning.intent}</span>}
            {typeof meaning.confidence === "number" && !corrected && (
              <span className="text-[#5F6368]">
                · {Math.round(meaning.confidence * 100)}% confidence
              </span>
            )}
          </div>

          {meaning.problem && (
            <p className="text-[12px] leading-5 text-[#202124]">
              <span className="font-medium">Complaint:</span> {meaning.problem}
            </p>
          )}

          {(meaning.asks ?? []).length > 0 && (
            <p className="text-[12px] leading-5 text-[#202124]">
              <span className="font-medium">Asking for:</span>{" "}
              {(meaning.asks ?? []).join(" · ")}
            </p>
          )}

          {evidence.length > 0 && (
            <div className="rounded-md border border-[#E8EAED] bg-white px-2.5 py-2">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-[#5F6368]">
                Evidence — copied from the review
              </p>
              <ul className="mt-1 space-y-0.5">
                {evidence.map((span, i) => (
                  <li key={i} className="text-[12px] leading-5 text-[#202124]" dir="auto">
                    “{span}”
                  </li>
                ))}
              </ul>
            </div>
          )}

          {evidence.length === 0 && meaning.source !== "human" && (
            <p className="text-[11px] leading-4 text-[#B06000]">
              No verbatim evidence was found, so this reading is not trusted. Check
              the review and correct it.
            </p>
          )}

          {needsHuman && !corrected && (
            <p className="text-[11px] leading-4 text-[#7A4F01]">
              {meaning.reason || "The AI was not confident about this one."} It is held
              out of the themes until someone checks it.
            </p>
          )}

          {corrected && meaning.correction_note && (
            <p className="text-[11px] leading-4 text-[#137333]/80">
              Note: {meaning.correction_note}
            </p>
          )}
        </div>
      )}

      {open && (
        <div className="mt-3 space-y-2.5 border-t border-[#DADCE0] pt-3">
          <p className="text-[11px] leading-4 text-[#5F6368]">
            The report builds its themes from this. Fixing it here fixes the report —
            it is not overwritten by the next re-analysis.
          </p>

          <label className="block">
            <span className="text-[12px] font-medium text-[#202124]">Subject</span>
            <select
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="mt-1 w-full rounded-md border border-[#DADCE0] bg-white px-2.5 py-2 text-[13px] text-[#202124] outline-none focus:border-[#1A73E8]"
            >
              {MEANING_SUBJECTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="text-[12px] font-medium text-[#202124]">
              The complaint, in their words
            </span>
            <textarea
              value={problem}
              onChange={(e) => setProblem(e.target.value)}
              rows={2}
              maxLength={1000}
              dir="auto"
              placeholder="What is this review actually about?"
              className="mt-1 w-full resize-y rounded-md border border-[#DADCE0] bg-white px-2.5 py-2 text-[13px] leading-5 text-[#202124] outline-none focus:border-[#1A73E8]"
            />
          </label>

          <div className="flex items-center justify-end gap-2">
            <button
              onClick={() => setOpen(false)}
              disabled={saving}
              className="rounded-md px-3 py-1.5 text-[12px] font-medium text-[#5F6368] hover:bg-ink/[0.04] disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="rounded-md bg-[#1A73E8] px-4 py-1.5 text-[12px] font-medium text-white transition hover:bg-[#1765CC] disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save correction"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
