"use client";

import { platforms } from "./platforms";

const recentVideos = [
  { title: "Product Demo - Feature Update", date: "2 hours ago", status: "posted" as const, platformSlugs: ["youtube", "instagram", "tiktok"] },
  { title: "Behind the Scenes - Team Day", date: "1 day ago", status: "posted" as const, platformSlugs: ["instagram", "facebook", "linkedin"] },
  { title: "Customer Testimonial Series", date: "3 days ago", status: "draft" as const, platformSlugs: [] },
  { title: "How-To Guide - Getting Started", date: "5 days ago", status: "posted" as const, platformSlugs: ["youtube", "x"] },
];

export default function RecentVideos() {
  return (
    <div>
      <h2 className="mb-3 text-[14px] font-bold text-ink">Recent Videos</h2>
      <div className="rounded-2xl border-2 border-white bg-white/80 overflow-hidden">
        {recentVideos.map((video, i) => (
          <div key={i} className={`flex items-center gap-4 px-4 py-3 ${i < recentVideos.length - 1 ? "border-b border-ink/[0.04]" : ""}`}>
            <div className="h-12 w-20 shrink-0 rounded-lg bg-ink/[0.06] flex items-center justify-center">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-5 w-5 text-ink/20">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[12px] font-semibold text-ink truncate">{video.title}</p>
              <p className="text-[10px] text-ink/40">{video.date}</p>
            </div>
            <div className="flex items-center gap-1.5">
              {video.platformSlugs.map((p) => {
                const pl = platforms.find((x) => x.slug === p);
                if (!pl) return null;
                return (
                  <div key={p} className="h-5 w-5 rounded-full flex items-center justify-center" style={{ backgroundColor: pl.color + "20" }}>
                    <svg viewBox="0 0 24 24" fill={pl.color} className="h-3 w-3">
                      <path d={pl.icon} />
                    </svg>
                  </div>
                );
              })}
            </div>
            <span className={`rounded-full px-2 py-0.5 text-[9px] font-semibold ${video.status === "posted" ? "bg-emerald-100 text-emerald-600" : "bg-amber-100 text-amber-600"}`}>
              {video.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
