"use client";

import { useState } from "react";
import {
  approveReply,
  editReply,
  generateReply,
  regenerateReply,
  rejectReply,
} from "@/lib/api-analytics";

type Phase = "idle" | "generating" | "editing" | "publishing" | "done";

const btn =
  "rounded-lg px-3 py-1.5 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-40";

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
      <p className="mt-2 flex items-center gap-1.5 text-[11px] font-semibold text-emerald">
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
          className={`${btn} bg-deep-violet text-white shadow-sm shadow-deep-violet/20 hover:bg-deep-violet/90`}
        >
          {phase === "generating" ? "Drafting..." : "Reply with AI"}
        </button>
        {error && <p className="mt-1 text-[10px] text-coral">{error}</p>}
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-xl border border-deep-violet/[0.12] bg-deep-violet/[0.02] p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] font-semibold text-deep-violet">AI draft — review before publishing</p>
        {dirty && <span className="text-[10px] font-medium text-amber-600">unsaved edits</span>}
      </div>
      <textarea
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          setDirty(true);
        }}
        rows={4}
        aria-label="Reply draft"
        className="w-full resize-y rounded-lg border border-deep-violet/[0.1] bg-white p-2.5 text-[12px] leading-relaxed text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1]"
      />
      {error && <p className="mt-1 text-[10px] text-coral">{error}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button
          onClick={() => {
            if (!replyId) return;
            setPhase("publishing");
            run(() => approveReply(channelId, replyId));
          }}
          disabled={busy}
          className={`${btn} bg-emerald text-white hover:bg-emerald/90`}
        >
          {phase === "publishing" ? "Publishing..." : "Approve & publish"}
        </button>
        <button
          onClick={() => {
            if (!replyId || !dirty) return;
            setPhase("publishing");
            run(() => editReply(channelId, replyId, draft));
          }}
          disabled={busy || !dirty}
          className={`${btn} bg-deep-violet/[0.07] text-deep-violet hover:bg-deep-violet/[0.12]`}
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
          className={`${btn} bg-deep-violet/[0.07] text-deep-violet hover:bg-deep-violet/[0.12]`}
        >
          Regenerate
        </button>
        <button
          onClick={discard}
          disabled={busy}
          className={`${btn} text-coral hover:bg-coral/[0.06]`}
        >
          Discard
        </button>
      </div>
    </div>
  );
}
