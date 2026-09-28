"use client";

import { useEffect, useState } from "react";
import { fetchFeedbackStatus, submitFeedback } from "@/lib/api-feedback";

const EMOJIS = [
  { rating: 1, emoji: "\u{1F61E}", label: "Very unhappy" },
  { rating: 2, emoji: "\u{1F610}", label: "Unhappy" },
  { rating: 3, emoji: "\u{1F642}", label: "Neutral" },
  { rating: 4, emoji: "\u{1F604}", label: "Happy" },
  { rating: 5, emoji: "\u{1F929}", label: "Very happy" },
];

type Phase = "loading" | "rate" | "message" | "submitting" | "done" | "cooldown";

/**
 * Feedback form rendered inline inside the Ask Sayvors sidebar — it no
 * longer floats over the page, so it can never sit on top of the chat.
 * The backend enforces a 24h cooldown per user; the status endpoint
 * tells us up front whether this user can still submit.
 */
export default function FeedbackPanel({ onClose }: { onClose: () => void }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [selectedRating, setSelectedRating] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [cooldownHours, setCooldownHours] = useState(24);
  const busy = phase === "submitting";

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await fetchFeedbackStatus();
        if (cancelled) return;
        if (typeof status.cooldown_hours === "number") setCooldownHours(status.cooldown_hours);
        setPhase(status.can_submit ? "rate" : "cooldown");
      } catch {
        if (!cancelled) setPhase("rate");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSubmit() {
    if (selectedRating === null) return;
    setPhase("submitting");
    setError(null);
    try {
      await submitFeedback({
        emoji_rating: selectedRating,
        message: message.trim() || undefined,
      });
      setPhase("done");
    } catch {
      setError("Could not send feedback. Try again.");
      setPhase("message");
    }
  }

  return (
    <div className="flex h-full flex-col bg-white dark:bg-ink">
      <div className="flex items-center gap-2.5 border-b border-ink/[0.06] bg-deep-violet px-4 py-3 dark:border-fog/[0.06]">
        <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white/15">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-white" aria-hidden>
            <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3Z" />
          </svg>
        </span>
        <p className="flex-1 text-[13px] font-bold text-white">Feedback</p>
        <button
          onClick={onClose}
          aria-label="Close feedback"
          className="rounded-lg p-1.5 text-white/70 outline-none transition hover:bg-white/10 hover:text-white focus-visible:ring-2 focus-visible:ring-white/40"
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4" aria-hidden>
            <path d="M5 5l10 10M15 5L5 15" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {phase === "loading" ? (
          <div className="space-y-2" aria-hidden>
            <div className="h-4 w-40 animate-pulse rounded bg-ink/[0.06]" />
            <div className="h-16 w-full animate-pulse rounded-xl bg-ink/[0.04]" />
          </div>
        ) : phase === "done" ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <span className="text-[32px]">{"\u{1F44D}"}</span>
            <p className="text-[14px] font-semibold text-ink dark:text-fog">Thank you for your feedback!</p>
            <p className="text-[11px] text-ink/45 dark:text-fog/45">It helps us make Sayvors better.</p>
            <button
              onClick={onClose}
              className="mt-1 rounded-lg bg-deep-violet px-3.5 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
            >
              Back to chat
            </button>
          </div>
        ) : phase === "cooldown" ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <span className="text-[28px]">{"\u{1F4DD}"}</span>
            <p className="text-[13px] font-semibold text-ink dark:text-fog">Thanks — you already shared feedback</p>
            <p className="max-w-[16rem] text-[11px] leading-relaxed text-ink/45 dark:text-fog/45">
              You can send another response in {cooldownHours} hours. We read every one.
            </p>
            <button
              onClick={onClose}
              className="mt-1 rounded-lg bg-deep-violet px-3.5 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
            >
              Back to chat
            </button>
          </div>
        ) : phase === "message" ? (
          <>
            <p className="mb-3 flex items-center gap-2 text-[13px] font-bold text-ink dark:text-fog">
              <span className="text-[20px]">{EMOJIS.find((e) => e.rating === selectedRating)?.emoji}</span>
              Tell us more (optional)
            </p>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={5}
              maxLength={2000}
              placeholder="What did you like? What could be better?"
              className="w-full resize-y rounded-lg border border-ink/10 bg-white p-2.5 text-[12px] leading-relaxed text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            />
            {error && <p className="mt-1.5 text-[11px] text-coral">{error}</p>}
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => setPhase("rate")}
                disabled={busy}
                className="flex-1 rounded-lg border border-ink/10 px-3 py-2.5 text-[12px] font-semibold text-ink/50 transition hover:bg-ink/[0.04] disabled:opacity-50 dark:border-fog/10 dark:text-fog/50"
              >
                Back
              </button>
              <button
                onClick={() => void handleSubmit()}
                disabled={busy}
                className="flex-1 rounded-lg bg-deep-violet px-3 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/25 transition hover:bg-deep-violet/90 disabled:opacity-50"
              >
                {busy ? "Sending…" : "Send feedback"}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="mb-1 text-[13px] font-bold text-ink dark:text-fog">How is your experience?</p>
            <p className="mb-4 text-[11px] text-ink/45 dark:text-fog/45">One tap — it takes a second.</p>
            <div className="grid grid-cols-5 gap-1">
              {EMOJIS.map((e) => (
                <button
                  key={e.rating}
                  onClick={() => {
                    setSelectedRating(e.rating);
                    setPhase("message");
                  }}
                  aria-label={e.label}
                  className="flex flex-col items-center gap-1 rounded-xl p-2 transition hover:bg-deep-violet/[0.06] focus-visible:ring-2 focus-visible:ring-deep-violet/40"
                >
                  <span className="text-[26px] transition hover:scale-110">{e.emoji}</span>
                  <span className="text-center text-[8px] font-medium leading-tight text-ink/40 dark:text-fog/40">
                    {e.label}
                  </span>
                </button>
              ))}
            </div>
            <button
              onClick={onClose}
              className="mt-5 w-full rounded-lg px-3 py-2 text-[12px] font-semibold text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink/60 dark:text-fog/40"
            >
              Maybe later
            </button>
          </>
        )}
      </div>
    </div>
  );
}
