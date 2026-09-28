"use client";

import { useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

interface AdminFeedback {
  id: string;
  user_id: string;
  emoji_rating: number;
  message: string | null;
  created_at: string | null;
}

const EMOJI_MAP: Record<number, string> = {
  1: "\u{1F61E}",
  2: "\u{1F610}",
  3: "\u{1F642}",
  4: "\u{1F604}",
  5: "\u{1F929}",
};

const PAGE_SIZE = 25;

export default function AdminFeedbackPage() {
  const [items, setItems] = useState<AdminFeedback[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) });
    adminFetch<{ total: number; items: AdminFeedback[] }>(`/api/v1/admin/feedback?${q.toString()}`)
      .then((d) => {
        if (!cancelled) {
          setItems(d.items);
          setTotal(d.total);
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page]);

  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="space-y-4 p-4 sm:p-6">
      <div>
        <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">User Feedback</h1>
        <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">
          Feedback submitted by users through the emoji widget
        </p>
      </div>

      <div className="rounded-[6px] border-2 border-white bg-white/80 p-4 shadow-sm backdrop-blur-sm sm:p-5">
        {loading ? (
          <div className="space-y-3" aria-hidden>
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className="h-12 animate-pulse rounded-[6px] bg-ink/[0.05]" />
            ))}
          </div>
        ) : error ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <p className="text-[13px] font-semibold text-ink/60">Could not load feedback.</p>
            <button
              onClick={() => {
                setError(null);
                setPage(0);
              }}
              className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white transition hover:bg-deep-violet/90"
            >
              Try again
            </button>
          </div>
        ) : items.length === 0 ? (
          <p className="py-8 text-center text-[13px] text-ink/40">No feedback submitted yet.</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-[12px]">
                <thead>
                  <tr className="border-b border-ink/[0.06] text-[10px] font-bold uppercase tracking-wide text-ink/40">
                    <th className="pb-2 pr-4">Emoji</th>
                    <th className="pb-2 pr-4">Rating</th>
                    <th className="pb-2 pr-4">Message</th>
                    <th className="pb-2 pr-4">User ID</th>
                    <th className="pb-2">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink/[0.04]">
                  {items.map((f) => (
                    <tr key={f.id} className="align-top">
                      <td className="py-2.5 pr-4 text-[20px]">{EMOJI_MAP[f.emoji_rating] ?? "\u{1F610}"}</td>
                      <td className="py-2.5 pr-4 font-semibold text-ink">{f.emoji_rating}/5</td>
                      <td className="max-w-xs py-2.5 pr-4">
                        <p className="line-clamp-2 text-ink/70">{f.message ?? "—"}</p>
                      </td>
                      <td className="py-2.5 pr-4 font-mono text-[10px] text-ink/40">{f.user_id.slice(0, 8)}…</td>
                      <td className="py-2.5 text-ink/50">
                        {f.created_at ? new Date(f.created_at).toLocaleString() : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {pages > 1 && (
              <div className="mt-4 flex items-center justify-between">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="rounded-lg px-3 py-1.5 text-[11px] font-semibold text-deep-violet transition enabled:hover:bg-deep-violet/[0.06] disabled:opacity-30"
                >
                  Previous
                </button>
                <span className="text-[11px] text-ink/40">Page {page + 1} of {pages}</span>
                <button
                  onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
                  disabled={page >= pages - 1}
                  className="rounded-lg px-3 py-1.5 text-[11px] font-semibold text-deep-violet transition enabled:hover:bg-deep-violet/[0.06] disabled:opacity-30"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
