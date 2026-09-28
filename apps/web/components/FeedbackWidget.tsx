"use client";

import { useState } from "react";
import { submitFeedback } from "@/lib/api-feedback";

const EMOJIS = [
  { rating: 1, emoji: "\u{1F61E}", label: "Very unhappy" },
  { rating: 2, emoji: "\u{1F610}", label: "Unhappy" },
  { rating: 3, emoji: "\u{1F642}", label: "Neutral" },
  { rating: 4, emoji: "\u{1F604}", label: "Happy" },
  { rating: 5, emoji: "\u{1F929}", label: "Very happy" },
];

type Phase = "closed" | "open" | "message" | "submitting" | "done";

export default function FeedbackWidget() {
  const [phase, setPhase] = useState<Phase>("closed");
  const [selectedRating, setSelectedRating] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleEmojiClick = (rating: number) => {
    setSelectedRating(rating);
    setPhase("message");
  };

  const handleSubmit = async () => {
    if (selectedRating === null) return;
    setPhase("submitting");
    setError(null);
    try {
      await submitFeedback({
        emoji_rating: selectedRating,
        message: message.trim() || undefined,
      });
      setPhase("done");
      setTimeout(() => {
        setPhase("closed");
        setSelectedRating(null);
        setMessage("");
      }, 2000);
    } catch {
      setError("Could not send feedback. Try again.");
      setPhase("message");
    }
  };

  if (phase === "closed") {
    return (
      <button
        onClick={() => setPhase("open")}
        aria-label="Give feedback"
        className="fixed bottom-4 right-20 z-50 flex h-14 w-14 items-center justify-center rounded-full bg-deep-violet text-white shadow-lg shadow-deep-violet/30 transition hover:scale-105 hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 active:scale-95"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5" aria-hidden>
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
          <path d="M12 2v16M2 9.27l6.91-1.01M22 9.27l-5 4.87" strokeWidth="1" strokeOpacity="0.4" />
        </svg>
      </button>
    );
  }

  return (
    <div className="fixed bottom-20 right-4 z-50 w-[calc(100vw-2rem)] max-w-xs rounded-2xl border-2 border-white bg-white/95 p-3 shadow-xl shadow-deep-violet/10 backdrop-blur-sm sm:bottom-4 sm:right-24 sm:max-w-sm sm:p-4">
      {phase === "done" ? (
        <div className="flex flex-col items-center gap-2 py-4 text-center">
          <span className="text-[24px]">{"\u{1F44D}"}</span>
          <p className="text-[13px] font-semibold text-ink">Thank you for your feedback!</p>
        </div>
      ) : phase === "message" ? (
        <>
          <div className="mb-3 flex items-center justify-between">
            <p className="text-[13px] font-bold text-ink">Tell us more (optional)</p>
            <button
              onClick={() => setPhase("open")}
              className="rounded-lg px-2 py-1 text-[11px] font-semibold text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink"
            >
              Back
            </button>
          </div>
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            rows={3}
            maxLength={2000}
            placeholder="What did you like? What could be better?"
            className="w-full resize-none rounded-lg border border-ink/10 bg-white p-2.5 text-[12px] leading-relaxed text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1]"
          />
          {error && <p className="mt-1 text-[10px] text-coral">{error}</p>}
          <div className="mt-2 flex gap-2">
            <button
              onClick={() => setPhase("open")}
              className="flex-1 rounded-lg border border-ink/10 px-3 py-2 text-[11px] font-semibold text-ink/50 transition hover:bg-ink/[0.04]"
            >
              Skip
            </button>
            <button
              onClick={handleSubmit}
              className="flex-1 rounded-lg bg-deep-violet px-3 py-2 text-[11px] font-bold text-white shadow-sm shadow-deep-violet/25 transition hover:bg-deep-violet/90 disabled:opacity-50"
            >
              Send feedback
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="mb-3 flex items-center justify-between">
            <p className="text-[13px] font-bold text-ink">How is your experience?</p>
            <button
              onClick={() => setPhase("closed")}
              className="rounded-lg px-2 py-1 text-[11px] font-semibold text-ink/40 transition hover:bg-ink/[0.04] hover:text-ink"
            >
              Close
            </button>
          </div>
          <div className="flex justify-between gap-0.5">
            {EMOJIS.map((e) => (
              <button
                key={e.rating}
                onClick={() => handleEmojiClick(e.rating)}
                aria-label={e.label}
                className="flex flex-1 flex-col items-center gap-0.5 rounded-xl p-1.5 transition hover:bg-deep-violet/[0.06] focus-visible:ring-2 focus-visible:ring-deep-violet/40 sm:gap-1 sm:p-2"
              >
                <span className="text-[22px] transition hover:scale-110 sm:text-[28px]">{e.emoji}</span>
                <span className="hidden text-[9px] font-medium text-ink/40 sm:block">{e.label}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
