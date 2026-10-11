"use client";

import { useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import {
  approveReply,
  editReply,
  generateReply,
  regenerateReply,
  rejectReply,
} from "@/lib/api-analytics";

type Phase = "idle" | "manual" | "generating" | "editing" | "publishing" | "done";

/* Team-ui button base: .ui-btn owns border, radius, hover-invert and disabled
 * states — no shadows, no hue. Fill/text per variant in the classNames below. */
const btn =
  "ui-btn rounded-[2px] px-3 py-1.5 text-[11px] font-semibold focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

export function ReplyComposer({
  channelId,
  reviewId,
  rating,
  reviewText,
  reviewerName,
  onPublished,
}: {
  channelId: string;
  reviewId: string;
  rating: number;
  reviewText: string | null;
  reviewerName: string | null;
  onPublished: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [replyId, setReplyId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<{ id: string; reply_text: string; status: string }>) {
    setError(null);
    try {
      const reply = await fn();
      setReplyId(reply.id);
      setDraft(reply.reply_text);
      setDirty(false);
      if (reply.status === "posted") {
        setPhase("done");
        onPublished();
      } else {
        setPhase("editing");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Something went wrong");
      setPhase(replyId ? "editing" : "idle");
    }
  }

  async function discard() {
    if (!replyId) return;
    setError(null);
    try {
      await rejectReply(channelId, replyId);
      setReplyId(null);
      setDraft("");
      setDirty(false);
      setPhase("idle");
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Could not discard");
      setPhase("editing");
    }
  }

  const busy = phase === "generating" || phase === "publishing";

  if (phase === "done") {
    return (
      <p className="mt-2 flex items-center gap-1.5 text-[11px] font-semibold text-[var(--ui-ink)]">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3" aria-hidden>
          <polyline points="20 6 9 17 4 12" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Reply published to Google
      </p>
    );
  }

  if (phase === "idle" || phase === "generating") {
    return (
      <div className="mt-2">
        <p className="mb-1.5 text-[11px] text-[var(--ui-ink-2)]">How do you want to answer this review?</p>
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => {
              setPhase("generating");
              run(() =>
                generateReply(channelId, {
                  review_id: reviewId,
                  rating,
                  review_text: reviewText,
                  reviewer_name: reviewerName,
                })
              );
            }}
            disabled={busy}
            className={`${btn} bg-[var(--ui-ink)] text-[var(--ui-on-ink)]`}
          >
            {phase === "generating" ? (
              <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Drafting...</span>
            ) : "AI writes it"}
          </button>
          <button
            onClick={() => {
              setError(null);
              setDraft("");
              setPhase("manual");
            }}
            disabled={busy}
            className={`${btn} text-[var(--ui-ink)]`}
          >
            I&apos;ll type it
          </button>
        </div>
        {error && <p className="mt-1 text-[10px] font-semibold text-[var(--ui-ink)]">{error}</p>}
      </div>
    );
  }

  if (phase === "manual") {
    const canSave = draft.trim().length >= 2;
    return (
      <div className="mt-2">
        <p className="mb-1.5 text-[11px] text-[var(--ui-ink-2)]">Type your reply — it will wait for approval like any other.</p>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder="Thank you so much for visiting us…"
          aria-label="Type your reply"
          autoFocus
          className="ui-input w-full resize-y bg-[var(--ui-surface)] p-2.5 text-[12px] leading-relaxed text-[var(--ui-ink)] placeholder:text-[var(--ui-ink-2)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        />
        {error && <p className="mt-1 text-[10px] font-semibold text-[var(--ui-ink)]">{error}</p>}
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          <button
            onClick={() => {
              setError(null);
              setDraft("");
              setPhase("idle");
            }}
            className={`${btn} text-[var(--ui-ink-2)]`}
          >
            Back
          </button>
          <button
            onClick={() => {
              setPhase("generating");
              run(() =>
                generateReply(channelId, {
                  review_id: reviewId,
                  rating,
                  review_text: reviewText,
                  reviewer_name: reviewerName,
                  custom_text: draft.trim(),
                })
              );
            }}
            disabled={!canSave}
            className={`${btn} bg-[var(--ui-ink)] text-[var(--ui-on-ink)]`}
          >
            Save for approval
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] font-semibold text-[var(--ui-ink)]">AI draft — review before publishing</p>
        {dirty && <span className="text-[10px] font-medium text-[var(--ui-ink-2)]">unsaved edits</span>}
      </div>
      <textarea
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          setDirty(true);
        }}
        rows={4}
        aria-label="Reply draft"
        className="ui-input w-full resize-y bg-[var(--ui-surface)] p-2.5 text-[12px] leading-relaxed text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
      />
      {error && <p className="mt-1 text-[10px] font-semibold text-[var(--ui-ink)]">{error}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button
          onClick={() => {
            if (!replyId) return;
            setPhase("publishing");
            run(() => approveReply(channelId, replyId));
          }}
          disabled={busy}
          className={`${btn} bg-[var(--ui-ink)] text-[var(--ui-on-ink)]`}
        >
          {phase === "publishing" ? (
            <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Publishing...</span>
          ) : "Approve & publish"}
        </button>
        <button
          onClick={() => {
            if (!replyId || !dirty) return;
            setPhase("publishing");
            run(() => editReply(channelId, replyId, draft));
          }}
          disabled={busy || !dirty}
          className={`${btn} bg-[var(--ui-surface)] text-[var(--ui-ink)]`}
        >
          Save edits
        </button>
        <button
          onClick={() => {
            if (!replyId) return;
            setPhase("publishing");
            run(() => regenerateReply(channelId, replyId));
          }}
          disabled={busy}
          className={`${btn} bg-[var(--ui-surface)] text-[var(--ui-ink)]`}
        >
          Regenerate
        </button>
        <button
          onClick={discard}
          disabled={busy}
          className="ui-btn-danger rounded-[2px] px-3 py-1.5 text-[11px] font-semibold focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] disabled:cursor-not-allowed disabled:opacity-45"
        >
          Discard
        </button>
      </div>
    </div>
  );
}
