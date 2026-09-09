"use client";

import Image from "next/image";
import { useState } from "react";

export interface GoogleReview {
  id: string;
  reviewer: string;
  rating: number;
  comment: string;
  createdAt: string;
  locationName: string;
  replied: boolean;
  sentiment?: string;
  reviewUrl?: string;
}

const AVATAR_COLORS = [
  "from-violet-500 to-deep-violet",
  "from-emerald-500 to-teal-600",
  "from-amber-500 to-orange-600",
  "from-sky-500 to-blue-600",
  "from-pink-500 to-magenta",
  "from-cyan-500 to-sky-600",
];

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "G";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function avatarColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

const DICEBEAR_BGS = ["5b2d8e", "0d9488", "d97706", "0284c7", "db2777", "0891b2"];

function avatarBg(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return DICEBEAR_BGS[h % DICEBEAR_BGS.length];
}

function ReviewerAvatar({ name }: { name: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return (
      <span
        aria-hidden
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-[13px] font-bold text-white shadow-sm ${avatarColor(name)}`}
      >
        {initials(name)}
      </span>
    );
  }
  return (
    <img
      src={`https://api.dicebear.com/9.x/initials/svg?seed=${encodeURIComponent(name)}&backgroundColor=${avatarBg(name)}&fontWeight=600`}
      alt=""
      aria-hidden
      width={40}
      height={40}
      onError={() => setFailed(true)}
      className="h-10 w-10 shrink-0 rounded-full shadow-sm ring-1 ring-ink/[0.08] dark:ring-fog/10"
      loading="lazy"
    />
  );
}

function relativeDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  const days = Math.floor((Date.now() - d.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) return `${Math.floor(days / 7)} wk ago`;
  return d.toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" });
}

export function GoogleWordmark({ className = "text-[13px]" }: { className?: string }) {
  return (
    <span aria-hidden className={`font-semibold tracking-tight ${className}`}>
      <span className="text-[#4285F4]">G</span>
      <span className="text-[#EA4335]">o</span>
      <span className="text-[#FBBC05]">o</span>
      <span className="text-[#4285F4]">g</span>
      <span className="text-[#34A853]">l</span>
      <span className="text-[#EA4335]">e</span>
    </span>
  );
}

export function GoogleStars({ rating, size = "h-4 w-4" }: { rating: number; size?: string }) {
  return (
    <span className="flex items-center gap-0.5" role="img" aria-label={`${rating} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((s) => (
        <svg
          key={s}
          viewBox="0 0 24 24"
          fill="currentColor"
          aria-hidden
          className={`${size} ${s <= Math.round(rating) ? "text-[#FBBC05]" : "text-ink/15 dark:text-fog/15"}`}
        >
          <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z" />
        </svg>
      ))}
    </span>
  );
}

export default function GoogleReviewCard({
  review,
  onOpen,
}: {
  review: GoogleReview;
  onOpen: (id: string) => void;
}) {
  const open = () => onOpen(review.id);
  return (
    <article
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={`Review by ${review.reviewer}, ${review.rating} stars. Open details.`}
      className="group w-full cursor-pointer rounded-2xl border border-ink/[0.06] bg-white p-4 text-left shadow-sm outline-none transition duration-200 hover:-translate-y-0.5 hover:border-[#4285F4]/30 hover:shadow-lg hover:shadow-[#4285F4]/[0.08] focus-visible:ring-2 focus-visible:ring-[#4285F4]/40 dark:border-fog/[0.06] dark:bg-ink"
    >
      {/* Header: avatar + identity + Google mark */}
      <div className="flex items-start gap-3">
        <ReviewerAvatar name={review.reviewer} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-bold text-ink dark:text-fog">{review.reviewer}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-ink/45 dark:text-fog/45">
            <span>{relativeDate(review.createdAt)}</span>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1">
              Posted on <GoogleWordmark className="text-[11px]" />
            </span>
          </p>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white shadow-sm ring-1 ring-ink/[0.08] transition group-hover:scale-105 dark:bg-fog/[0.06] dark:ring-fog/10">
          <Image src="/google.svg" alt="Google" width={20} height={20} className="h-5 w-5" />
        </span>
      </div>

      {/* Stars + message */}
      <div className="mt-3">
        <GoogleStars rating={review.rating} />
        <p className="mt-1.5 line-clamp-3 text-[13px] leading-relaxed text-ink/80 dark:text-fog/80">
          &ldquo;{review.comment}&rdquo;
        </p>
      </div>

      {/* Footer: location + status + link */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ink/[0.05] pt-3 dark:border-fog/[0.06]">
        <span className="min-w-0 flex-1 truncate text-[11px] text-ink/40 dark:text-fog/40">
          {review.locationName}
        </span>
        {review.sentiment && (
          <span className="rounded-full bg-deep-violet/[0.07] px-2 py-0.5 text-[10px] font-semibold capitalize text-deep-violet">
            {review.sentiment}
          </span>
        )}
        {review.replied ? (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
            Replied
          </span>
        ) : (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
            Needs reply
          </span>
        )}
        {review.reviewUrl && (
          <a
            href={review.reviewUrl}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="rounded-full px-2 py-0.5 text-[10px] font-bold text-[#4285F4] transition hover:bg-[#4285F4]/10"
          >
            View on Google →
          </a>
        )}
      </div>
    </article>
  );
}
