"use client";

import Link from "next/link";
import PlatformIcon from "./PlatformIcon";
import { platforms } from "./platforms";

const platformStats: Record<string, { videos: number; views: string; engagement: string }> = {
  youtube: { videos: 12, views: "45.2K", engagement: "8.3%" },
  instagram: { videos: 8, views: "32.1K", engagement: "12.5%" },
  tiktok: { videos: 15, views: "128.7K", engagement: "22.1%" },
  facebook: { videos: 6, views: "18.9K", engagement: "6.7%" },
  linkedin: { videos: 4, views: "8.4K", engagement: "5.2%" },
  x: { videos: 10, views: "56.3K", engagement: "9.8%" },
};

export default function PlatformGrid() {
  return (
    <div>
      <h2 className="mb-3 text-[14px] font-bold text-ink">Platform Performance</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {platforms.map((platform) => {
          const stat = platformStats[platform.slug];
          return (
            <Link
              key={platform.slug}
              href={`/dashboard/video-studio/${platform.slug}`}
              className="group rounded-2xl border-2 border-white bg-white/80 p-4 transition hover:border-deep-violet/20 hover:shadow-md"
            >
              <div className="flex items-center gap-3">
                <PlatformIcon slug={platform.slug} icon={platform.icon} color={platform.color} />
                <div className="flex-1">
                  <h3 className="text-[13px] font-bold text-ink group-hover:text-deep-violet transition">{platform.name}</h3>
                  <p className="text-[11px] text-ink/45">{stat?.videos || 0} videos</p>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <div className="rounded-lg bg-ink/[0.03] px-3 py-1.5">
                  <p className="text-[10px] text-ink/40">Views</p>
                  <p className="text-[12px] font-bold text-ink">{stat?.views || "0"}</p>
                </div>
                <div className="rounded-lg bg-ink/[0.03] px-3 py-1.5">
                  <p className="text-[10px] text-ink/40">Engagement</p>
                  <p className="text-[12px] font-bold text-emerald-600">{stat?.engagement || "0%"}</p>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
