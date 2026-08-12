"use client";

import Link from "next/link";
import type { Video } from "./platforms";

interface VideoListItemProps {
  video: Video;
  platformSlug: string;
  platformColor: string;
}

export default function VideoListItem({ video, platformSlug, platformColor }: VideoListItemProps) {
  return (
    <Link
      href={`/dashboard/video-studio/${platformSlug}/video/${video.id}`}
      className="group flex items-center gap-4 px-4 py-3 transition hover:bg-deep-violet/[0.03] border-b border-ink/[0.04] last:border-b-0"
    >
      {/* Thumbnail */}
      <div
        className="h-14 w-24 shrink-0 rounded-xl flex items-center justify-center"
        style={{ backgroundColor: video.thumbnailColor + "15" }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5" style={{ color: video.thumbnailColor }}>
          <polygon points="5 3 19 12 5 21 5 3" fill="currentColor" opacity="0.5" />
        </svg>
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="text-[12px] font-semibold text-ink group-hover:text-deep-violet transition truncate">{video.title}</p>
        <p className="text-[10px] text-ink/40 mt-0.5">{video.publishedAt}</p>
      </div>

      {/* Stats */}
      <div className="hidden sm:flex items-center gap-4 shrink-0">
        <div className="text-right">
          <p className="text-[11px] font-bold text-ink">{video.views}</p>
          <p className="text-[9px] text-ink/35">views</p>
        </div>
        <div className="text-right">
          <p className="text-[11px] font-bold text-ink">{video.likes}</p>
          <p className="text-[9px] text-ink/35">likes</p>
        </div>
        <div className="text-right">
          <p className="text-[11px] font-bold text-ink">{video.retention}</p>
          <p className="text-[9px] text-ink/35">retention</p>
        </div>
      </div>

      {/* Status */}
      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-semibold ${
        video.status === "published" ? "bg-emerald-100 text-emerald-600" :
        video.status === "scheduled" ? "bg-amber-100 text-amber-600" :
        "bg-ink/10 text-ink/50"
      }`}>
        {video.status}
      </span>

      {/* Arrow */}
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5 text-ink/20 shrink-0 group-hover:text-deep-violet transition">
        <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </Link>
  );
}
