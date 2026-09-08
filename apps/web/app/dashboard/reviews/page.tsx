"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type ReviewTab = "all" | "unanswered" | "replied" | "positive" | "negative";
type View = { kind: "list" } | { kind: "detail"; id: string };

interface ReviewItem {
  id: string;
  locationId: string;
  locationName: string;
  reviewer: string;
  rating: number;
  comment: string;
  createdAt: string;
  reply?: string;
  replyUpdatedAt?: string;
  reviewReplyUrl?: string;
  policyStatus?: "OK" | "FLAGGED";
}

interface LocationOption {
  id: string;
  name: string;
}

const MOCK_LOCATIONS: LocationOption[] = [
  { id: "loc_1", name: "Sayvors Al Malqa" },
  { id: "loc_2", name: "Sayvors Olaya" },
];

const PAGE_SIZE = 4;

const MOCK_REVIEWS: ReviewItem[] = [  {
    id: "r1", locationId: "loc_1", locationName: "Sayvors Al Malqa",
    reviewer: "John Smith", rating: 5, comment: "Great service and very helpful staff. Highly recommended!",
    createdAt: "2026-09-08", reply: "Thank you for visiting us!",
    replyUpdatedAt: "2026-09-08", reviewReplyUrl: "https://g.page/review/r1/reply",
    policyStatus: "OK",
  },
  {
    id: "r2", locationId: "loc_1", locationName: "Sayvors Al Malqa",
    reviewer: "Sara Ahmed", rating: 5, comment: "Excellent service, quick response.",
    createdAt: "2026-09-06",
  },
  {
    id: "r3", locationId: "loc_2", locationName: "Sayvors Olaya",
    reviewer: "Omar K.", rating: 2, comment: "Waited too long, staff seemed busy.",
    createdAt: "2026-09-04", reply: "Sorry about the wait — we are fixing staffing this week.",
    replyUpdatedAt: "2026-09-05", policyStatus: "OK",
  },
  {
    id: "r4", locationId: "loc_1", locationName: "Sayvors Al Malqa",
    reviewer: "Lina M.", rating: 1, comment: "Not happy with the support.",
    createdAt: "2026-09-02",
  },
  {
    id: "r5", locationId: "loc_2", locationName: "Sayvors Olaya",
    reviewer: "Fahad R.", rating: 4, comment: "Good experience overall.",
    createdAt: "2026-08-28", reply: "Thanks Fahad!",
    replyUpdatedAt: "2026-08-29", policyStatus: "OK",
  },
  {
    id: "r6", locationId: "loc_1", locationName: "Sayvors Al Malqa",
    reviewer: "Nora S.", rating: 3, comment: "Average, could be better.",
    createdAt: "2026-08-20",
  },
];

export default function ReviewsPage() {
  return (
    <Suspense>
      <ReviewsInner />
    </Suspense>
  );
}

function ReviewsInner() {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reviews, setReviews] = useState<ReviewItem[]>([]);
  const [tab, setTab] = useState<ReviewTab>("all");
  const [view, setView] = useState<View>({ kind: "list" });
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [replyDraft, setReplyDraft] = useState("");
  const [replying, setReplying] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [replyMode, setReplyMode] = useState<"manual" | "ai">("manual");
  const [aiLoading, setAiLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/locations/?limit=100");
        if (!cancelled) {
          const locs = data.locations ?? MOCK_LOCATIONS;
          setLocations(locs);
          if (locs.length) setSelectedId(locs[0].id);
        }
      } catch {
        setLocations(MOCK_LOCATIONS);
        setSelectedId(MOCK_LOCATIONS[0].id);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const fetchReviews = async () => {
    if (!selectedId) return;
    setRefreshing(true);
    try {
      const data = await apiFetch(`/api/v1/locations/${selectedId}/reviews`);
      setReviews(normalizeReviews(data.reviews) ?? MOCK_REVIEWS);
    } catch {
      setReviews(MOCK_REVIEWS);
    }
    setRefreshing(false);
  };

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch(`/api/v1/locations/${selectedId}/reviews`);
        if (!cancelled) setReviews(normalizeReviews(data.reviews) ?? MOCK_REVIEWS);
      } catch {
        if (!cancelled) setReviews(MOCK_REVIEWS);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const counts = useMemo(() => ({
    all: reviews.length,
    unanswered: reviews.filter((r) => !r.reply).length,
    replied: reviews.filter((r) => r.reply).length,
    positive: reviews.filter((r) => r.rating >= 4).length,
    negative: reviews.filter((r) => r.rating <= 2).length,
  }), [reviews]);

  const filtered = reviews.filter((r) => {
    if (tab === "unanswered") return !r.reply;
    if (tab === "replied") return !!r.reply;
    if (tab === "positive") return r.rating >= 4;
    if (tab === "negative") return r.rating <= 2;
    return true;
  });

  const active = view.kind === "detail" ? reviews.find((r) => r.id === view.id) ?? null : null;

  const openDetail = (id: string) => {
    const r = reviews.find((x) => x.id === id);
    setReplyDraft(r?.reply ?? "");
    setReplyMode("manual");
    setView({ kind: "detail", id });
  };

  const generateAiReply = async () => {
    if (view.kind !== "detail") return;
    const r = reviews.find((x) => x.id === view.id);
    if (!r) return;
    setAiLoading(true);
    setReplyMode("ai");
    // Frontend-only draft; backend AI endpoint can replace this later.
    await new Promise((res) => setTimeout(res, 900));
    const tone = r.rating >= 4
      ? `Thank you so much, ${r.reviewer}! We're thrilled you enjoyed ${r.locationName}.`
      : r.rating === 3
        ? `Thanks for your honest feedback, ${r.reviewer}. We'll work on doing better at ${r.locationName}.`
        : `We're really sorry about your experience, ${r.reviewer}. Our team at ${r.locationName} will reach out and make this right.`;
    const extra = r.rating >= 4
      ? " Hope to see you again soon!"
      : " Please give us another chance to improve.";
    setReplyDraft(`${tone}${extra}`);
    setAiLoading(false);
  };

  const saveReply = async (isEdit: boolean) => {
    if (view.kind !== "detail" || !replyDraft.trim()) return;
    setReplying(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/reviews/${view.id}/reply`, {
        method: isEdit ? "PATCH" : "POST",
        body: JSON.stringify({ reply: replyDraft.trim() }),
      });
    } catch { /* optimistic, frontend-only for now */ }
    setReviews((prev) => prev.map((r) => r.id === view.id
      ? { ...r, reply: replyDraft.trim(), replyUpdatedAt: new Date().toISOString().slice(0, 10), policyStatus: "OK" as const }
      : r));
    setReplying(false);
    setBanner({ kind: "ok", text: isEdit ? "Reply updated." : "Reply posted." });
    setTimeout(() => setBanner(null), 2500);
  };

  const deleteReply = async (id: string) => {
    if (!confirm("Delete your reply to this review? The review itself stays.")) return;
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/reviews/${id}/reply`, { method: "DELETE" });
    } catch { /* optimistic */ }
    setReviews((prev) => prev.map((r) => r.id === id ? { ...r, reply: undefined, replyUpdatedAt: undefined } : r));
    setReplyDraft("");
    setBanner({ kind: "ok", text: "Reply deleted." });
    setTimeout(() => setBanner(null), 2500);
  };

  const analytics = useMemo(() => {
    const total = reviews.length;
    const dist = [5, 4, 3, 2, 1].map((s) => ({ stars: s, count: reviews.filter((r) => r.rating === s).length }));
    const avg = total ? reviews.reduce((a, r) => a + r.rating, 0) / total : 0;
    const replied = reviews.filter((r) => r.reply).length;
    const thisMonth = reviews.filter((r) => r.createdAt.slice(0, 7) === "2026-09").length;
    const lastMonth = reviews.filter((r) => r.createdAt.slice(0, 7) === "2026-08").length;
    const months = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"].map((m) => ({
      label: m.slice(5),
      count: reviews.filter((r) => r.createdAt.slice(0, 7) === m).length,
    }));
    const maxMonth = Math.max(1, ...months.map((m) => m.count));
    return { total, dist, avg, replied, responseRate: total ? Math.round((replied / total) * 100) : 0, thisMonth, lastMonth, months, maxMonth };
  }, [reviews]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paged = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const pickTab = (t: ReviewTab) => {
    setTab(t);
    setPage(1);
  };

  if (loading) return <div className="flex h-full items-center justify-center"><LogoLoader size={32} /></div>;

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-ink/[0.06] bg-white/80 px-6 py-4 backdrop-blur dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-[18px] font-bold text-ink dark:text-fog">Reviews</h1>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">
              {counts.all} total · {counts.unanswered} unanswered · {counts.replied} replied
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <select value={selectedId ?? ""} onChange={(e) => { setSelectedId(e.target.value); setPage(1); setView({ kind: "list" }); }}
                className="w-52 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog">
                {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <button onClick={fetchReviews} disabled={refreshing} className="btn-secondary disabled:opacity-50">
              {refreshing ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Syncing...</span> : "Reconcile"}
            </button>
          </div>
        </div>
        {banner && (
          <div className={`mt-3 rounded-lg px-3 py-1.5 text-[12px] font-medium ${banner.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{banner.text}</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-3xl space-y-4">
          {view.kind === "detail" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">Reviews</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="font-semibold text-ink dark:text-fog">Review details</span>
            </nav>
          )}

          {view.kind === "list" && (
            <>
              {/* Insights */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatCard label="Average Rating" value={`${analytics.avg.toFixed(1)} ★`} />
                <StatCard label="Total Reviews" value={String(analytics.total)} />
                <StatCard label="Response Rate" value={`${analytics.responseRate}%`} />
                <StatCard label="Unanswered" value={String(counts.unanswered)} />
              </div>

              {/* Charts */}
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                  <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Rating breakdown</h3>
                  <p className="text-[11px] text-ink/35">Sayvors-derived.</p>
                  <div className="mt-3 space-y-2">
                    {analytics.dist.map((d) => (
                      <div key={d.stars} className="flex items-center gap-2">
                        <span className="w-8 text-[11px] font-medium text-ink/50">{d.stars} ★</span>
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
                          <div className="h-full rounded-full bg-gradient-to-r from-[#FBBC05] to-[#EA4335]" style={{ width: `${analytics.total ? (d.count / analytics.total) * 100 : 0}%` }} />
                        </div>
                        <span className="w-8 text-right text-[11px] text-ink/50">{d.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                  <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Reviews trend</h3>
                  <p className="text-[11px] text-ink/35">Last 6 months · this {analytics.thisMonth} / last {analytics.lastMonth}.</p>
                  <div className="mt-3 flex h-24 items-end gap-2">
                    {analytics.months.map((m) => (
                      <div key={m.label} className="flex flex-1 flex-col items-center gap-1">
                        <div className="flex w-full flex-1 items-end rounded-md bg-ink/[0.04] dark:bg-fog/[0.05]">
                          <div className="w-full rounded-md bg-deep-violet/70" style={{ height: `${Math.max(6, (m.count / analytics.maxMonth) * 100)}%` }} />
                        </div>
                        <span className="text-[9px] text-ink/40">{m.label}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="flex gap-1 overflow-x-auto rounded-xl bg-ink/[0.03] p-1 dark:bg-fog/[0.04]">
                {([
                  { key: "all", label: `All (${counts.all})` },
                  { key: "unanswered", label: `Unanswered (${counts.unanswered})` },
                  { key: "replied", label: `Replied (${counts.replied})` },
                  { key: "positive", label: `Positive (${counts.positive})` },
                  { key: "negative", label: `Negative (${counts.negative})` },
                ] as const).map((t) => (
                  <button key={t.key} onClick={() => pickTab(t.key)}
                    className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-semibold transition ${tab === t.key ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-fog" : "text-ink/45 hover:text-ink/70 dark:text-fog/45"}`}>
                    {t.label}
                  </button>
                ))}
              </div>

              {filtered.length === 0 ? (
                <div className="flex flex-col items-center rounded-2xl border border-dashed border-ink/[0.12] bg-white py-16 dark:border-fog/[0.12] dark:bg-ink">
                  <p className="text-[14px] font-medium text-ink/40">No reviews in this view</p>
                </div>
              ) : (
                <>
                  <div className="space-y-2">
                    {paged.map((r) => (
                      <button key={r.id} onClick={() => openDetail(r.id)} className="block w-full rounded-2xl border border-ink/[0.06] bg-white p-4 text-left transition hover:border-deep-violet/25 hover:shadow-sm dark:border-fog/[0.06] dark:bg-ink">
                        <span className="flex items-start justify-between gap-3">
                          <span>
                            <span className="block text-[13px] font-bold text-ink dark:text-fog">{r.reviewer}</span>
                            <span className="block text-[10px] text-ink/35">{r.locationName} · {r.createdAt}</span>
                          </span>
                          <Stars rating={r.rating} />
                        </span>
                        <span className="mt-2 line-clamp-2 block text-[13px] leading-relaxed text-ink/70">“{r.comment}”</span>
                        <span className="mt-2 block text-[11px]">
                          {r.reply
                            ? <span className="rounded-full bg-emerald-100 px-2 py-0.5 font-semibold text-emerald-700">Replied</span>
                            : <span className="rounded-full bg-amber-100 px-2 py-0.5 font-semibold text-amber-700">Needs reply</span>}
                        </span>
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center justify-between pt-1">
                    <p className="text-[11px] text-ink/40">Page {safePage} of {totalPages} · {filtered.length} reviews</p>
                    <div className="flex gap-1">
                      <button onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage <= 1} className="btn-secondary !px-3 !py-1.5 disabled:opacity-40">Prev</button>
                      {Array.from({ length: totalPages }).slice(0, 5).map((_, i) => (
                        <button key={i} onClick={() => setPage(i + 1)}
                          className={`rounded-lg px-2.5 py-1.5 text-[12px] font-semibold ${safePage === i + 1 ? "bg-deep-violet text-white" : "text-ink/50 hover:bg-ink/[0.04]"}`}>
                          {i + 1}
                        </button>
                      ))}
                      <button onClick={() => setPage(Math.min(totalPages, safePage + 1))} disabled={safePage >= totalPages} className="btn-secondary !px-3 !py-1.5 disabled:opacity-40">Next</button>
                    </div>
                  </div>
                </>
              )}
            </>
          )}

          {view.kind === "detail" && active && (
            <div className="space-y-3">
              <div className="rounded-2xl border border-ink/[0.06] bg-white p-6 dark:border-fog/[0.06] dark:bg-ink">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-[15px] font-bold text-ink dark:text-fog">{active.reviewer}</h2>
                    <p className="text-[11px] text-ink/40">{active.locationName} · {active.createdAt}</p>
                  </div>
                  <Stars rating={active.rating} />
                </div>
                <p className="mt-3 text-[14px] leading-relaxed text-ink dark:text-fog">“{active.comment}”</p>

                <div className="mt-5 border-t border-ink/[0.05] pt-4">
                  <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Your reply</h3>
                  <div className="mt-2 flex gap-1 rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.05]">
                    <button onClick={() => setReplyMode("manual")}
                      className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-semibold transition ${replyMode === "manual" ? "bg-white text-deep-violet shadow-sm dark:bg-ink" : "text-ink/45"}`}>
                      Write myself
                    </button>
                    <button onClick={() => generateAiReply()}
                      className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-semibold transition ${replyMode === "ai" ? "bg-white text-deep-violet shadow-sm dark:bg-ink" : "text-ink/45"}`}>
                      Write with AI
                    </button>
                  </div>
                  {active.reply && !replyEditing(active.reply, replyDraft) && replyMode === "manual" ? (
                    <div className="mt-2 rounded-xl bg-ink/[0.03] p-3 dark:bg-fog/[0.04]">
                      <p className="text-[13px] text-ink dark:text-fog">“{active.reply}”</p>
                      {active.replyUpdatedAt && <p className="mt-1 text-[10px] text-ink/35">Replied {active.replyUpdatedAt}</p>}
                    </div>
                  ) : null}
                  {aiLoading ? (
                    <div className="mt-2 flex items-center gap-2 rounded-xl border border-deep-violet/15 bg-deep-violet/[0.04] p-3">
                      <LogoLoader size={16} />
                      <p className="text-[12px] text-ink/50">AI is drafting a reply...</p>
                    </div>
                  ) : (
                    <textarea
                      value={replyDraft}
                      onChange={(e) => { setReplyDraft(e.target.value); setReplyMode("manual"); }}
                      rows={3}
                      maxLength={1000}
                      placeholder={replyMode === "ai" ? "AI draft — edit if you like, then submit..." : active.reply ? "Edit your reply..." : "Write your reply..."}
                      className="input-field mt-2 resize-y"
                    />
                  )}
                  {replyMode === "ai" && !aiLoading && (
                    <button onClick={() => generateAiReply()} className="mt-1 text-[11px] font-semibold text-deep-violet hover:underline">Regenerate AI draft</button>
                  )}
                  <div className="mt-2 flex flex-wrap gap-2">
                    <button onClick={() => saveReply(!!active.reply)} disabled={!replyDraft.trim() || replying || aiLoading} className="btn-primary disabled:opacity-50">
                      {replying ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : "Submit"}
                    </button>
                    {active.reply && (
                      <button onClick={() => deleteReply(active.id)} className="rounded-xl border border-red-200 px-4 py-2 text-[12px] font-semibold text-red-600 hover:bg-red-50">
                        Delete Reply
                      </button>
                    )}
                  </div>
                  <p className="mt-2 text-[10px] text-ink/30">Type yourself, or tap Write with AI and just hit Submit. Customer reviews cannot be deleted or edited.</p>
                </div>

                <div className="mt-4 grid grid-cols-2 gap-3 border-t border-ink/[0.05] pt-4 text-[11px]">
                  <div>
                    <p className="text-ink/40">Policy status</p>
                    <p className="font-semibold text-ink dark:text-fog">{active.policyStatus ?? "—"}</p>
                  </div>
                  <div>
                    <p className="text-ink/40">Reply URL</p>
                    <p className="truncate font-semibold text-ink dark:text-fog">{active.reviewReplyUrl ?? "—"}</p>
                  </div>
                </div>
              </div>
              <button onClick={() => setView({ kind: "list" })} className="text-[12px] font-medium text-ink/40 hover:text-ink">← Back to reviews</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function replyEditing(saved: string, draft: string) {
  return saved !== draft;
}

function normalizeReviews(raw: unknown): ReviewItem[] | null {
  if (!Array.isArray(raw)) return null;
  return raw.map((r: Record<string, unknown>, i: number) => ({
    id: String(r.id ?? `r_${i}`),
    locationId: String(r.locationId ?? r.location_id ?? "loc_1"),
    locationName: String(r.locationName ?? r.location_name ?? ""),
    reviewer: String(r.reviewer ?? r.reviewer_name ?? "Customer"),
    rating: Number(r.rating ?? r.star_rating ?? 5),
    comment: String(r.comment ?? r.text ?? ""),
    createdAt: String(r.createdAt ?? r.created_at ?? ""),
    reply: r.reply ? String(r.reply) : undefined,
    replyUpdatedAt: r.replyUpdatedAt ? String(r.replyUpdatedAt) : undefined,
    reviewReplyUrl: r.reviewReplyUrl ? String(r.reviewReplyUrl) : undefined,
    policyStatus: r.policyStatus === "FLAGGED" ? "FLAGGED" : r.policyStatus === "OK" ? "OK" : undefined,
  }));
}

function Stars({ rating }: { rating: number }) {
  return (
    <span className="flex shrink-0 gap-0.5" aria-label={`${rating} stars`}>
      {[1, 2, 3, 4, 5].map((s) => (
        <svg key={s} viewBox="0 0 24 24" className={`h-3.5 w-3.5 ${s <= rating ? "text-[#FBBC05]" : "text-ink/15 dark:text-fog/15"}`} fill="currentColor">
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
        </svg>
      ))}
    </span>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-ink/[0.06] bg-white p-3 dark:border-fog/[0.06] dark:bg-ink">
      <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">{label}</p>
      <p className="text-[18px] font-bold text-ink dark:text-fog">{value}</p>
    </div>
  );
}
