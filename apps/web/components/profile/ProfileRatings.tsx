"use client";

import { useState } from "react";
import LogoLoader from "@/components/LogoLoader";

const FEATURES = [
  { id: "overall", label: "Overall experience" },
  { id: "ai", label: "AI agent quality" },
  { id: "ui", label: "User interface" },
  { id: "support", label: "Customer support" },
  { id: "value", label: "Value for money" },
];

export default function ProfileRatings({
  ratings,
  savingKey,
  onRate,
}: {
  ratings: Record<string, number>;
  savingKey: string | null;
  onRate: (category: string, stars: number) => Promise<void>;
}) {
  const [hovered, setHovered] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  async function handleRate(id: string, stars: number) {
    if (ratings[id] === stars) return;
    setError(null);
    try {
      await onRate(id, stars);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save rating.");
    }
  }

  return (
    <section aria-label="Feedback" className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm">
      <div className="mb-1">
        <h3 className="text-[14px] font-bold text-ink">Feedback</h3>
        <p className="text-[11px] text-ink/45">Tap a star — it saves instantly.</p>
      </div>

      <div className="divide-y divide-ink/[0.06]">
        {FEATURES.map((f) => {
          const value = ratings[f.id] ?? 0;
          const hover = hovered[f.id] ?? 0;
          const busy = savingKey === f.id;
          return (
            <div key={f.id} className="flex items-center justify-between gap-3 py-3">
              <span className="text-[13px] font-medium text-ink">
                {f.label}
                {busy && (
                  <span className="ml-2 inline-flex items-center gap-1 text-[10px] font-semibold text-ink/35">
                    <LogoLoader size={12} /> Saving…
                  </span>
                )}
              </span>
              <div className="flex items-center gap-0.5" role="radiogroup" aria-label={f.label}>
                {[1, 2, 3, 4, 5].map((star) => {
                  const lit = (hover || value) >= star;
                  return (
                    <button
                      key={star}
                      role="radio"
                      aria-checked={value === star}
                      aria-label={`${star} star${star > 1 ? "s" : ""}`}
                      disabled={busy}
                      onMouseEnter={() => setHovered((p) => ({ ...p, [f.id]: star }))}
                      onMouseLeave={() => setHovered((p) => ({ ...p, [f.id]: 0 }))}
                      onFocus={() => setHovered((p) => ({ ...p, [f.id]: star }))}
                      onBlur={() => setHovered((p) => ({ ...p, [f.id]: 0 }))}
                      onClick={() => handleRate(f.id, star)}
                      className="rounded p-0.5 transition hover:scale-110 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/60 disabled:opacity-60"
                    >
                      <svg
                        viewBox="0 0 24 24"
                        fill={lit ? "#f59e0b" : "none"}
                        stroke={lit ? "#f59e0b" : "#d1d5db"}
                        strokeWidth="1.5"
                        className="h-5 w-5"
                        aria-hidden
                      >
                        <path
                          d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {error && <p role="alert" className="mt-2 text-[12px] font-medium text-coral">{error}</p>}
    </section>
  );
}
