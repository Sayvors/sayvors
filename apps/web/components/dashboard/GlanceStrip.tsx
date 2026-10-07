"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { apiFetch } from "@/lib/api-rag";
import { fetchOverview } from "@/lib/api-analytics";

interface BizRow {
  id: string;
  name: string;
  reviews: number | null;
  rating: number | null;
}

const platformConfig = [
  { key: "whatsapp", label: "WhatsApp", bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/20" },
  { key: "instagram", label: "Instagram", bg: "bg-pink-500/10", text: "text-pink-400", border: "border-pink-500/20" },
  { key: "facebook", label: "Messenger", bg: "bg-blue-500/10", text: "text-blue-400", border: "border-blue-500/20" },
] as const;

function PlatformIcon({ name }: { name: string }) {
  const icons: Record<string, React.ReactElement> = {
    whatsapp: (
      <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 0 1-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 0 1-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 0 1 2.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0 0 12.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 0 0 5.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 0 0-3.48-8.413Z" />
      </svg>
    ),
    instagram: (
      <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
        <path d="M12 0C8.74 0 8.333.015 7.053.072 5.775.132 4.905.333 4.14.63c-.789.306-1.459.717-2.126 1.384S.935 3.35.63 4.14C.333 4.905.132 5.775.072 7.053.012 8.333 0 8.74 0 12s.015 3.667.072 4.947c.06 1.277.261 2.148.558 2.913.306.788.718 1.459 1.384 2.126.667.666 1.336 1.079 2.126 1.384.766.296 1.636.499 2.913.558C8.333 23.988 8.74 24 12 24s3.667-.015 4.947-.072c1.277-.06 2.148-.262 2.913-.558.788-.306 1.459-.718 2.126-1.384.666-.667 1.079-1.335 1.384-2.126.296-.765.499-1.636.558-2.913.06-1.28.072-1.687.072-4.947s-.015-3.667-.072-4.947c-.06-1.277-.262-2.149-.558-2.913-.306-.789-.718-1.459-1.384-2.126C21.319 1.347 20.651.935 19.86.63c-.765-.297-1.636-.499-2.913-.558C15.667.012 15.26 0 12 0m0 2.16c1.402 0 1.592.002 2.12.03 1.393.053 2.08.21 2.45.344a3.88 3.88 0 0 1 1.316.86c.364.363.627.783.86 1.316.134.37.291 1.057.344 2.45.028.528.03.718.03 2.12s-.002 1.592-.03 2.12c-.053 1.393-.21 2.08-.344 2.45a3.88 3.88 0 0 1-.86 1.316 3.88 3.88 0 0 1-1.316.86c-.37.134-1.057.291-2.45.344-.528.028-.718.03-2.12.03s-1.592-.002-2.12-.03c-1.393-.053-2.08-.21-2.45-.344a3.88 3.88 0 0 1-1.316-.86 3.88 3.88 0 0 1-.86-1.316c-.134-.37-.291-1.057-.344-2.45C2.162 13.592 2.16 13.402 2.16 12s.002-1.592.03-2.12c.053-1.393.21-2.08.344-2.45a3.88 3.88 0 0 1 .86-1.316A3.88 3.88 0 0 1 5.4 3.66c.37-.134 1.057-.291 2.45-.344C8.408 2.162 8.598 2.16 12 2.16" />
        <path d="M12 5.838a6.162 6.162 0 1 0 0 12.324 6.162 6.162 0 0 0 0-12.324M12 16a4 4 0 1 1 0-8 4 4 0 0 1 0 8m6.406-11.845a1.44 1.44 0 1 0 0 2.881 1.44 1.44 0 0 0 0-2.881" />
      </svg>
    ),
    facebook: (
      <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
        <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073" />
      </svg>
    ),
  };
  return <span className="inline-flex">{icons[name] ?? null}</span>;
}

export default function GlanceStrip() {
  const [platformMsgs, setPlatformMsgs] = useState<Record<string, number>>({});
  const [biz, setBiz] = useState<BizRow[]>([]);
  const [totalReviews, setTotalReviews] = useState<number | null>(null);
  const [avgRating, setAvgRating] = useState<number | null>(null);
  const [postStats, setPostStats] = useState<{ total: number; published: number; scheduled: number; draft: number } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Messages per platform from inbox threads.
      try {
        const data = await apiFetch("/api/v1/inbox/threads?limit=500");
        const threads = (data?.threads ?? []) as { platform: string | null; message_count: number }[];
        const per: Record<string, number> = {};
        for (const t of threads) {
          const p = t.platform ?? "unknown";
          per[p] = (per[p] ?? 0) + (t.message_count ?? 0);
        }
        if (!cancelled) setPlatformMsgs(per);
      } catch {
        /* leave empty */
      }

      // Per-business reviews + rating via each Google channel's overview.
      try {
        const chans = await apiFetch("/api/v1/channels?limit=100");
        const list = (Array.isArray(chans) ? chans : (chans?.channels ?? [])) as {
          id: string; display_name: string | null; platform?: string | null;
        }[];
        const google = list.filter((c) => (c.platform ?? "").includes("google"));

        // Overall totals across every business.
        try {
          const overall = await fetchOverview(30, null);
          if (overall && !cancelled) {
            setTotalReviews(overall.total_reviews);
            setAvgRating(overall.avg_rating);
          }
        } catch {
          /* leave */
        }

        const rows: BizRow[] = [];
        await Promise.all(
          google.slice(0, 8).map(async (c) => {
            try {
              const o = await fetchOverview(30, c.id);
              if (o) {
                rows.push({ id: c.id, name: c.display_name ?? "Location", reviews: o.total_reviews, rating: o.avg_rating });
              }
            } catch {
              /* skip */
            }
          }),
        );
        if (!cancelled) setBiz(rows);
      } catch {
        /* leave empty */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/posts");
        if (cancelled) return;
        const rows = (Array.isArray(data) ? data : []) as Record<string, unknown>[];
        let published = 0, scheduled = 0, draft = 0;
        for (const p of rows) {
          const s = String(p.status ?? "");
          if (s === "published") published++;
          else if (s === "scheduled") scheduled++;
          else if (s === "draft") draft++;
        }
        setPostStats({ total: rows.length, published, scheduled, draft });
      } catch {
        /* leave empty */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const totalMsgs = (platformMsgs["whatsapp"] ?? 0) + (platformMsgs["instagram"] ?? 0) + (platformMsgs["facebook"] ?? 0);

  return (
    <section aria-label="Glance" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
      {/* Messages card — redesigned with icons, colors, and total */}
      <div className="rounded-[2px] border border-ink/[0.06] bg-white/80 p-4 backdrop-blur-sm dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Messages</p>
          <Image src="/meta.png" alt="Meta" width={32} height={32} />
        </div>
        <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{totalMsgs}</p>
        <div className="mt-3 space-y-2">
          {platformConfig.map(({ key, label, bg, text, border }) => (
            <div key={key} className={`flex items-center gap-2 rounded-[2px] border ${border} ${bg} px-2.5 py-1.5`}>
              <span className={`${text}`}><PlatformIcon name={key} /></span>
              <span className="flex-1 text-[12px] font-medium text-ink/70 dark:text-fog/70">{label}</span>
              <span className="text-[12px] font-bold text-ink dark:text-fog">{platformMsgs[key] ?? 0}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Tickets card — placeholder, no API call yet */}
      <div className="rounded-[2px] border border-ink/[0.06] bg-white/80 p-4 backdrop-blur-sm dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Tickets</p>
          <Image src="/leads.png" alt="Tickets" width={32} height={32} />
        </div>
        <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">0</p>
        <p className="mt-2 text-[11px] text-ink/40 dark:text-fog/40">All channels</p>
      </div>

      <div className="rounded-[2px] border border-ink/[0.06] bg-white/80 p-4 backdrop-blur-sm dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Reviews</p>
          <Image src="/google-review.png" alt="Google Reviews" width={32} height={32} />
        </div>
        <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{totalReviews ?? "-"}</p>
        <div className="mt-3 space-y-2">
          {biz.slice(0, 4).map((b) => (
            <div key={b.id} className="flex items-center gap-2 rounded-[2px] border border-amber-500/20 bg-amber-500/10 px-2.5 py-1.5">
              <span className="text-amber-400">
                <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                  <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 16.8l-6.2 4.5 2.4-7.4L2 9.4h7.6z" />
                </svg>
              </span>
              <span className="flex-1 truncate text-[12px] font-medium text-ink/70 dark:text-fog/70">{b.name}</span>
              <span className="text-[12px] font-bold text-ink dark:text-fog">{b.reviews ?? 0}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-[2px] border border-ink/[0.06] bg-white/80 p-4 backdrop-blur-sm dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex items-center justify-between">
          <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Avg rating</p>
          <Image src="/google-business.png" alt="Google Business" width={32} height={32} />
        </div>
        <p className="mt-1 text-[22px] font-bold text-amber-500">{avgRating != null ? avgRating.toFixed(1) : "-"}</p>
        <div className="mt-3 space-y-2">
          {biz.slice(0, 4).map((b) => (
            <div key={b.id} className="flex items-center gap-2 rounded-[2px] border border-amber-500/20 bg-amber-500/10 px-2.5 py-1.5">
              <span className="text-amber-400">
                <svg viewBox="0 0 24 24" fill="currentColor" className="h-4 w-4">
                  <path d="M12 2l2.4 7.4H22l-6.2 4.5 2.4 7.4L12 16.8l-6.2 4.5 2.4-7.4L2 9.4h7.6z" />
                </svg>
              </span>
              <span className="flex-1 truncate text-[12px] font-medium text-ink/70 dark:text-fog/70">{b.name}</span>
              <span className="text-[12px] font-bold text-ink dark:text-fog">{b.rating != null ? b.rating.toFixed(1) : "-"}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Posts card — everything in one view */}
      <Link href="/dashboard/posts-media" aria-label="Open posts and media">
        <div className="h-full rounded-[2px] border border-ink/[0.06] bg-white/80 p-4 backdrop-blur-sm transition hover:border-deep-violet/30 dark:border-fog/[0.06] dark:bg-ink/80">
          <div className="flex items-center justify-between">
            <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Posts</p>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5 text-deep-violet/70" aria-hidden>
              <rect x="3" y="4" width="18" height="17" rx="2" />
              <path d="M3 9h18M8 2v4M16 2v4" />
            </svg>
          </div>
          <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{postStats ? postStats.total : "-"}</p>
          {postStats ? (
            <div className="mt-3 space-y-1.5">
              <div className="flex items-center justify-between text-[12px]">
                <span className="text-ink/55 dark:text-fog/55">Published</span>
                <span className="font-bold text-ink dark:text-fog">{postStats.published}</span>
              </div>
              <div className="flex items-center justify-between text-[12px]">
                <span className="text-ink/55 dark:text-fog/55">Scheduled</span>
                <span className="font-bold text-deep-violet">{postStats.scheduled}</span>
              </div>
              <div className="flex items-center justify-between text-[12px]">
                <span className="text-ink/55 dark:text-fog/55">Draft</span>
                <span className="font-bold text-ink/60 dark:text-fog/60">{postStats.draft}</span>
              </div>
            </div>
          ) : (
            <p className="mt-2 text-[11px] text-ink/40">Loading…</p>
          )}
        </div>
      </Link>
    </section>
  );
}
