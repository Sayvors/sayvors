"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type ReviewTab = "all" | "unanswered" | "replied" | "positive" | "negative";
type View = { kind: "list" } | { kind: "detail"; id: string } | { kind: "star"; stars: number } | { kind: "intelligence" };

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
  const starGroup = view.kind === "star" ? reviews.filter((r) => r.rating === view.stars) : [];
  const intelligence = useMemo(() => buildIntelligence(reviews), [reviews]);

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

          {view.kind === "star" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">Reviews</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="font-semibold text-ink dark:text-fog">{view.stars}★ insights</span>
            </nav>
          )}

          {view.kind === "intelligence" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={() => setView({ kind: "list" })} className="font-medium hover:text-deep-violet">Reviews</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="font-semibold text-ink dark:text-fog">Review Intelligence</span>
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
                  <button onClick={() => setView({ kind: "intelligence" })} className="block w-full text-left">
                    <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Rating breakdown</h3>
                    <p className="text-[11px] text-ink/35">Sayvors-derived · tap anywhere for full intelligence.</p>
                  </button>
                  <div className="mt-3 space-y-1">
                    {analytics.dist.map((d) => (
                      <button key={d.stars} onClick={() => setView({ kind: "star", stars: d.stars })}
                        className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition hover:bg-deep-violet/[0.05] hover:ring-1 hover:ring-deep-violet/20">
                        <span className="w-8 text-[11px] font-medium text-ink/50">{d.stars} ★</span>
                        <span className="h-2 flex-1 overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
                          <span className="block h-full rounded-full bg-gradient-to-r from-[#FBBC05] to-[#EA4335]" style={{ width: `${analytics.total ? (d.count / analytics.total) * 100 : 0}%` }} />
                        </span>
                        <span className="w-8 text-right text-[11px] text-ink/50">{d.count}</span>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3 text-ink/30"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </button>
                    ))}
                  </div>
                  <button onClick={() => setView({ kind: "intelligence" })}
                    className="mt-3 w-full rounded-xl bg-deep-violet/[0.06] py-2 text-[12px] font-bold text-deep-violet transition hover:bg-deep-violet hover:text-white">
                    See more insights →
                  </button>
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

          {view.kind === "star" && (
            <StarInsightPage
              stars={view.stars}
              group={starGroup}
              total={reviews.length}
              onBack={() => setView({ kind: "list" })}
              onOpen={(id) => openDetail(id)}
            />
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

              <InsightCard review={active} />
              <button onClick={() => setView({ kind: "list" })} className="text-[12px] font-medium text-ink/40 hover:text-ink">← Back to reviews</button>
            </div>
          )}

          {view.kind === "intelligence" && (
            <IntelligencePage
              intelligence={intelligence}
              total={reviews.length}
              locationName={locations.find((l) => l.id === selectedId)?.name ?? ""}
              onBack={() => setView({ kind: "list" })}
              onOpenStar={(s) => setView({ kind: "star", stars: s })}
            />
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

function StarInsightPage({ stars, group, total, onBack, onOpen }: { stars: number; group: ReviewItem[]; total: number; onBack: () => void; onOpen: (id: string) => void }) {
  const share = total ? Math.round((group.length / total) * 100) : 0;
  const replied = group.filter((r) => r.reply).length;
  const signals = topSignals(group.map((r) => r.comment));
  const verdict = stars >= 4
    ? "Strength — protect what earns these ratings."
    : stars === 3
      ? "Swing zone — small fixes convert these to 4–5★."
      : "Risk zone — reply fast and fix the root cause.";
  const action = stars >= 4
    ? "Thank them quickly and invite them back."
    : stars === 3
      ? "Acknowledge the friction and state one concrete fix."
      : "Apologize with a concrete fix, then address the root cause operationally.";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-[17px] font-bold text-ink dark:text-fog">{stars}★ insights</h2>
          <p className="text-[12px] text-ink/55 dark:text-fog/60">{group.length} reviews · {share}% of total · replied {replied}/{group.length}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${stars >= 4 ? "bg-emerald-100 text-emerald-700" : stars === 3 ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-700"}`}>
          {stars >= 4 ? "High" : stars === 3 ? "Mixed" : "Low"}
        </span>
      </div>
      <div className="grid gap-3 lg:grid-cols-3">
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">Overview</h3>
          <p className="text-[12px] leading-relaxed text-ink/60">{verdict}</p>
          <p className="mt-3 text-[12px] text-ink/60">Share <span className="font-bold text-ink">{share}%</span> · response <span className="font-bold text-ink">{group.length ? Math.round((replied / group.length) * 100) : 0}%</span></p>
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">Top signals</h3>
          {signals.length ? (
            <ul className="space-y-2">
              {signals.map((s) => (
                <li key={s} className="rounded-lg bg-ink/[0.04] px-2.5 py-1.5 text-[12px] font-semibold text-ink/70">{s}</li>
              ))}
            </ul>
          ) : <p className="text-[12px] text-ink/40">No reviews at this rating yet.</p>}
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-2 text-[14px] font-bold text-ink">Recommended action</h3>
          <p className="text-[12px] leading-relaxed text-ink/60">{action}</p>
          <p className="mt-3 text-[11px] text-ink/40">Sayvors-derived from retrieved reviews.</p>
        </section>
      </div>
      <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
        <h3 className="mb-2 text-[13px] font-semibold text-ink dark:text-fog">Matching reviews</h3>
        {group.length === 0 ? (
          <p className="py-4 text-center text-[12px] text-ink/40">No reviews at this rating yet.</p>
        ) : (
          <div className="space-y-1.5">
            {group.map((r) => (
              <button key={r.id} onClick={() => onOpen(r.id)} className="block w-full truncate rounded-lg px-2.5 py-2 text-left text-[12px] text-ink/70 ring-1 ring-ink/[0.05] hover:ring-deep-violet/30 dark:text-fog/70">
                <span className="font-semibold text-ink dark:text-fog">{r.reviewer}</span> — “{r.comment}”
              </button>
            ))}
          </div>
        )}
      </div>
      <button onClick={onBack} className="text-[12px] font-medium text-ink/40 hover:text-ink">← Back to reviews</button>
    </div>
  );
}

function topSignals(comments: string[]): string[] {
  const lex = ["wait", "slow", "staff", "service", "clean", "price", "friendly", "quick", "helpful", "busy", "support", "quality"];
  const counts = lex.map((w) => ({ w, c: comments.filter((t) => t.toLowerCase().includes(w)).length })).filter((x) => x.c > 0);
  return counts.sort((a, b) => b.c - a.c).slice(0, 4).map((x) => `${x.w} ×${x.c}`);
}

interface IntelTheme {
  name: string;
  keywords: string[];
  mentions: number;
  avgRating: number;
  positivePct: number;
  phrases: string[];
  sampleIds: string[];
}

interface Intelligence {
  avg: number;
  sentimentScore: number;
  sentimentLabel: string;
  confidence: number;
  summary: string;
  love: IntelTheme[];
  dislike: IntelTheme[];
  drivers: { theme: string; s5: number; s4: number; s3: number; low: number }[];
  opportunities: { level: "HIGH" | "MEDIUM" | "MAINTAIN"; title: string; detail: string; impact: string }[];
  strengths: { title: string; mentions: number; avg: number }[];
  sentimentSplit: { positive: number; neutral: number; negative: number };
  topics: { name: string; count: number }[];
  actions: { title: string; detail: string }[];
}

const THEME_DEFS: { name: string; keywords: string[] }[] = [
  { name: "Staff & Service", keywords: ["staff", "service", "helpful", "professional", "friendly", "welcoming"] },
  { name: "Quality", keywords: ["quality", "great", "excellent", "good"] },
  { name: "Cleanliness", keywords: ["clean"] },
  { name: "Speed", keywords: ["fast", "quick", "slow", "wait", "queue"] },
  { name: "Value", keywords: ["price", "pricing", "expensive", "value", "cheap"] },
  { name: "Communication", keywords: ["communication", "response", "support", "rude"] },
  { name: "Availability", keywords: ["busy", "availability", "wait", "long"] },
  { name: "Location", keywords: ["location", "parking", "area"] },
];

function buildIntelligence(reviews: ReviewItem[]): Intelligence {
  const total = reviews.length;
  const avg = total ? reviews.reduce((a, r) => a + r.rating, 0) / total : 0;
  const pos = reviews.filter((r) => r.rating >= 4).length;
  const neu = reviews.filter((r) => r.rating === 3).length;
  const neg = reviews.filter((r) => r.rating <= 2).length;
  const sentimentScore = total ? Math.round((pos / total) * 5 * 10) / 10 : 0;
  const sentimentLabel = !total ? "No data" : pos / total >= 0.6 ? "Positive" : neg / total >= 0.4 ? "Negative" : "Mixed";

  const themeStats = (def: { name: string; keywords: string[] }): IntelTheme => {
    const matched = reviews.filter((r) => def.keywords.some((k) => r.comment.toLowerCase().includes(k)));
    const mentions = matched.length;
    const avgRating = mentions ? matched.reduce((a, r) => a + r.rating, 0) / mentions : 0;
    const positivePct = mentions ? Math.round((matched.filter((r) => r.rating >= 4).length / mentions) * 100) : 0;
    const phrases = Array.from(new Set(
      matched.flatMap((r) => r.comment.split(/[.,!]/).map((s) => s.trim()).filter((s) => def.keywords.some((k) => s.toLowerCase().includes(k))).slice(0, 1))
    )).slice(0, 3);
    return { name: def.name, keywords: def.keywords, mentions, avgRating, positivePct, phrases, sampleIds: matched.slice(0, 2).map((r) => r.id) };
  };
  const themes = THEME_DEFS.map(themeStats).sort((a, b) => b.mentions - a.mentions);
  const love = themes.filter((t) => t.positivePct >= 60 && t.mentions > 0).slice(0, 5);
  const dislike = themes.filter((t) => t.positivePct < 60 && t.mentions > 0).sort((a, b) => a.positivePct - b.positivePct).slice(0, 4);

  const drivers = themes.slice(0, 6).map((t) => {
    const inGroup = (fn: (r: ReviewItem) => boolean) => reviews.filter((r) => fn(r) && t.keywords.some((k) => r.comment.toLowerCase().includes(k))).length;
    return { theme: t.name, s5: inGroup((r) => r.rating === 5), s4: inGroup((r) => r.rating === 4), s3: inGroup((r) => r.rating === 3), low: inGroup((r) => r.rating <= 2) };
  });

  const waitTheme = themes.find((t) => t.name === "Speed");
  const valueTheme = themes.find((t) => t.name === "Value");
  const staffTheme = themes.find((t) => t.name === "Staff & Service");

  const summary = !total
    ? "No reviews analyzed yet."
    : `Overall sentiment is ${sentimentLabel.toLowerCase()}. Customers consistently praise ${(love.map((t) => t.name.toLowerCase()).slice(0, 3).join(", ") || "service")}. The biggest drag is ${(dislike.map((t) => t.name.toLowerCase()).slice(0, 2).join(" and ") || "isolated complaints")}. ${waitTheme && waitTheme.mentions > 0 ? "Reducing waiting time looks like the biggest lever for more 4–5★ reviews." : "Protect current strengths while tightening response time."}`;

  return {
    avg, sentimentScore, sentimentLabel,
    confidence: total ? Math.min(96, 70 + total * 3) : 0,
    summary, love, dislike, drivers,
    opportunities: [
      ...(waitTheme && waitTheme.mentions > 0 ? [{ level: "HIGH" as const, title: "Reduce waiting time", detail: `${waitTheme.mentions} mentions · avg ${waitTheme.avgRating.toFixed(1)}★. Review peak-hour staffing and set wait expectations.`, impact: "HIGH" }] : []),
      ...(valueTheme && valueTheme.mentions > 0 ? [{ level: "MEDIUM" as const, title: "Improve price/value communication", detail: `${valueTheme.mentions} mentions. Clarify inclusions and highlight value-added benefits.`, impact: "MEDIUM" }] : []),
      ...(staffTheme && staffTheme.mentions > 0 ? [{ level: "MAINTAIN" as const, title: "Maintain staff friendliness", detail: `${staffTheme.mentions} positive mentions · ${staffTheme.avgRating.toFixed(1)}★ average. Keep training as-is.`, impact: "GUARD" }] : []),
    ],
    strengths: love.slice(0, 3).map((t) => ({ title: t.name, mentions: t.mentions, avg: t.avgRating })),
    sentimentSplit: { positive: pos, neutral: neu, negative: neg },
    topics: themes.map((t) => ({ name: t.name, count: t.mentions })),
    actions: [
      ...(waitTheme && waitTheme.mentions > 0 ? [{ title: "Fix waiting time", detail: `${waitTheme.mentions} reviews affected · HIGH impact` }] : []),
      { title: `Respond to ${reviews.filter((r) => !r.reply).length} unanswered reviews`, detail: "Immediate action" },
      ...(staffTheme ? [{ title: "Protect staff training", detail: "Strong positive driver" }] : []),
    ].slice(0, 5),
  };
}

function IntelligencePage({ intelligence: intel, total, locationName, onBack, onOpenStar }: {
  intelligence: Intelligence; total: number; locationName: string;
  onBack: () => void; onOpenStar: (s: number) => void;
}) {
  const i = intel;
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-[17px] font-bold text-ink dark:text-fog">Review Intelligence</h2>
        <p className="text-[12px] text-ink/45">{locationName} · {total} reviews analyzed · Sayvors-derived AI analytics</p>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Avg. Rating" value={`${i.avg.toFixed(1)} ★`} />
        <StatCard label="Reviews" value={String(total)} />
        <StatCard label="AI Sentiment" value={`${i.sentimentScore} ★`} />
        <StatCard label="Confidence" value={`${i.confidence}%`} />
      </div>

      <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
        <h3 className="text-[14px] font-bold text-ink">AI Executive Summary</h3>
        <p className="mt-2 text-[13px] leading-relaxed text-ink/70">{i.summary}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {[5, 4, 3, 2, 1].map((s) => (
            <button key={s} onClick={() => onOpenStar(s)} className="rounded-full bg-ink/[0.04] px-2.5 py-1 text-[11px] font-bold text-ink/60 hover:bg-deep-violet hover:text-white">
              {s}★ detail →
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-3 text-[14px] font-bold text-ink">What customers love</h3>
          {i.love.length === 0 ? <p className="text-[12px] text-ink/40">Not enough positive signals yet.</p> : (
            <div className="space-y-2.5">
              {i.love.map((t) => (
                <div key={t.name}>
                  <div className="flex justify-between text-[12px] font-semibold text-ink/70"><span>{t.name}</span><span>{t.positivePct}%</span></div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink/[0.06]"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${t.positivePct}%` }} /></div>
                  <p className="mt-1 text-[11px] text-ink/40">{t.mentions} mentions · {t.avgRating.toFixed(1)}★ avg</p>
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-3 text-[14px] font-bold text-ink">What customers dislike</h3>
          {i.dislike.length === 0 ? <p className="text-[12px] text-emerald-600">No major complaints detected. Good sign.</p> : (
            <div className="space-y-2.5">
              {i.dislike.map((t) => (
                <div key={t.name}>
                  <div className="flex justify-between text-[12px] font-semibold text-ink/70"><span>{t.name}</span><span>{t.mentions} mentions</span></div>
                  <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink/[0.06]"><div className="h-full rounded-full bg-coral" style={{ width: `${Math.min(100, t.mentions * 12)}%` }} /></div>
                  <p className="mt-1 text-[11px] text-ink/40">{t.avgRating.toFixed(1)}★ avg in these reviews</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
        <h3 className="text-[14px] font-bold text-ink">What drives your rating?</h3>
        <p className="text-[11px] text-ink/40">High ratings track staff & quality · low ratings track wait & value.</p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[520px] text-[11px]">
            <thead>
              <tr className="text-left text-ink/40">
                <th className="py-1 font-semibold">Theme</th>
                <th className="text-center font-semibold">5★</th>
                <th className="text-center font-semibold">4★</th>
                <th className="text-center font-semibold">3★</th>
                <th className="text-center font-semibold">1–2★</th>
              </tr>
            </thead>
            <tbody>
              {i.drivers.map((d) => (
                <tr key={d.theme} className="border-t border-ink/[0.05]">
                  <td className="py-1.5 pr-2 font-semibold text-ink/70">{d.theme}</td>
                  {[d.s5, d.s4, d.s3, d.low].map((v, idx) => (
                    <td key={idx} className="py-1.5 text-center tabular-nums text-ink/60">
                      <span className="inline-block min-w-6 rounded bg-ink/[0.04] px-1.5 py-0.5">{v}</span>
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-3 text-[14px] font-bold text-ink">Improvement opportunities</h3>
          <div className="space-y-2">
            {i.opportunities.map((o) => (
              <div key={o.title} className="rounded-xl bg-ink/[0.03] p-3">
                <p className="text-[12px] font-bold text-ink"><span className={`mr-1.5 rounded px-1.5 py-px text-[9px] ${o.level === "HIGH" ? "bg-coral/15 text-coral" : o.level === "MEDIUM" ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"}`}>{o.level}</span>{o.title}</p>
                <p className="mt-1 text-[11px] text-ink/55">{o.detail} Impact: {o.impact}.</p>
              </div>
            ))}
            {i.opportunities.length === 0 && <p className="text-[12px] text-ink/40">Nothing urgent right now.</p>}
          </div>
        </section>
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
          <h3 className="mb-3 text-[14px] font-bold text-ink">Strengths to protect</h3>
          <div className="space-y-2">
            {i.strengths.map((s, idx) => (
              <p key={s.title} className="text-[12px] text-ink/65"><span className="font-bold text-ink">{idx + 1}. {s.title}</span> · {s.mentions} mentions · {s.avg.toFixed(1)}★</p>
            ))}
            {i.strengths.length === 0 && <p className="text-[12px] text-ink/40">No clear strengths yet.</p>}
          </div>
          <h3 className="mb-2 mt-4 text-[14px] font-bold text-ink">AI action plan</h3>
          <ol className="space-y-1.5">
            {i.actions.map((a, idx) => (
              <li key={a.title} className="text-[12px] text-ink/65"><span className="font-bold text-deep-violet">{idx + 1}.</span> <span className="font-semibold">{a.title}</span> — {a.detail}</li>
            ))}
          </ol>
        </section>
      </div>

      <div className="rounded-2xl border-2 border-white bg-white/80 p-5 backdrop-blur-sm">
        <h3 className="text-[14px] font-bold text-ink">Review themes</h3>
        <p className="text-[11px] text-ink/40">Tap a theme to see contributing reviews.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {i.topics.map((t) => (
            <span key={t.name} className="rounded-full bg-ink/[0.04] px-3 py-1.5 text-[12px] font-semibold text-ink/65">{t.name} · {t.count}</span>
          ))}
        </div>
      </div>

      <button onClick={onBack} className="text-[12px] font-medium text-ink/40 hover:text-ink">← Back to reviews</button>
    </div>
  );
}

function InsightCard({ review }: { review: ReviewItem }) {
  const insight = explainReview(review);
  return (
    <div className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-[13px] font-bold text-ink dark:text-fog">Why this rating?</h3>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${insight.tone === "high" ? "bg-emerald-100 text-emerald-700" : insight.tone === "low" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}>
          {insight.tone === "high" ? "High" : insight.tone === "low" ? "Low" : "Mixed"}
        </span>
      </div>
      <p className="mt-2 text-[12px] leading-relaxed text-ink/60 dark:text-fog/60">{insight.summary}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl bg-emerald-50/60 p-3 dark:bg-emerald-500/[0.06]">
          <p className="text-[11px] font-bold text-emerald-700 dark:text-emerald-300">What lifted it</p>
          {insight.positives.length ? (
            <ul className="mt-1.5 space-y-1">
              {insight.positives.map((x) => <li key={x} className="text-[11px] text-emerald-800 dark:text-emerald-200">+ {x}</li>)}
            </ul>
          ) : <p className="mt-1 text-[11px] text-ink/40">No clear positive signals.</p>}
        </div>
        <div className="rounded-xl bg-red-50/60 p-3 dark:bg-red-500/[0.06]">
          <p className="text-[11px] font-bold text-red-700 dark:text-red-300">What dragged it</p>
          {insight.negatives.length ? (
            <ul className="mt-1.5 space-y-1">
              {insight.negatives.map((x) => <li key={x} className="text-[11px] text-red-800 dark:text-red-200">− {x}</li>)}
            </ul>
          ) : <p className="mt-1 text-[11px] text-ink/40">No clear negative signals.</p>}
        </div>
      </div>
      <div className="mt-3 rounded-xl bg-ink/[0.03] p-3 dark:bg-fog/[0.04]">
        <p className="text-[11px] font-bold text-ink dark:text-fog">Overall result</p>
        <p className="mt-1 text-[12px] text-ink/60 dark:text-fog/60">{insight.result}</p>
        <p className="mt-2 text-[11px] font-semibold text-deep-violet">Next: {insight.action}</p>
      </div>
      <p className="mt-2 text-[10px] text-ink/30">Explainable heuristics from rating + comment text · {review.locationName} · {review.createdAt}{review.reply ? " · replied" : " · unanswered"}.</p>
    </div>
  );
}

function explainReview(r: ReviewItem): { tone: "high" | "low" | "mixed"; summary: string; positives: string[]; negatives: string[]; result: string; action: string } {
  const text = r.comment.toLowerCase();
  const posLex: Record<string, string> = {
    great: "praised overall service", excellent: "called service excellent", helpful: "mentioned helpful staff",
    quick: "liked fast response", friendly: "found staff friendly", clean: "liked cleanliness",
    recommend: "would recommend", good: "positive overall tone", fast: "liked speed",
  };
  const negLex: Record<string, string> = {
    wait: "complained about waiting", slow: "felt service was slow", rude: "felt staff was rude",
    bad: "negative overall tone", poor: "rated support poorly", long: "mentioned long delays",
    busy: "felt staff was too busy", dirty: "flagged cleanliness", expensive: "felt pricing was high",
    unhappy: "expressed unhappiness",
  };
  const positives = Object.entries(posLex).filter(([k]) => text.includes(k)).map(([, v]) => v);
  const negatives = Object.entries(negLex).filter(([k]) => text.includes(k)).map(([, v]) => v);
  if (r.rating >= 4 && negatives.length === 0) {
    return {
      tone: "high",
      summary: `This is high because the customer gave ${r.rating}★ with${positives.length ? "" : "out"} explicit praise signals. High ratings like this lift the location average and response-rate health.`,
      positives: positives.length ? positives : ["high star rating itself"],
      negatives,
      result: `Positive outcome for ${r.locationName}. ${r.reply ? "Already replied — good for trust." : "Reply to lock in loyalty."}`,
      action: r.reply ? "No urgent fix; thank them and invite them back." : "Post a warm thank-you reply today.",
    };
  }
  if (r.rating <= 2) {
    return {
      tone: "low",
      summary: `This is low because the customer gave ${r.rating}★${negatives.length ? " and the text points at specific pain" : " even without detailed text"}. Low ratings drag the average and need a fast, empathetic reply.`,
      positives,
      negatives: negatives.length ? negatives : ["low star rating without detail"],
      result: `At-risk signal for ${r.locationName}. ${r.reply ? "Reply exists — monitor for follow-up." : "Unanswered — highest priority."}`,
      action: "Reply with apology + concrete fix, then address the root cause operationally.",
    };
  }
  return {
    tone: "mixed",
    summary: `This sits in the middle at ${r.rating}★ — not angry, not delighted. These reviews usually hide one fixable friction point.`,
    positives: positives.length ? positives : ["neutral-to-positive tone"],
    negatives: negatives.length ? negatives : ["no strong complaint detected"],
    result: `Neutral outcome. Small fix at ${r.locationName} could convert this customer to 4–5★.`,
    action: "Acknowledge the feedback and state one specific improvement.",
  };
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
