"use client";

import type { PlatformAnalytics } from "./platforms";

interface PlatformStatsProps {
  analytics: PlatformAnalytics;
}

export default function PlatformStats({ analytics }: PlatformStatsProps) {
  const stats = [
    { label: "Followers", value: analytics.followers, icon: "👥" },
    { label: "Total Views", value: analytics.totalViews, icon: "👁️" },
    { label: "Engagement", value: analytics.avgEngagement, icon: "📈" },
    { label: "Avg Watch Time", value: analytics.avgWatchTime, icon: "⏱️" },
    { label: "Top Region", value: analytics.topRegion, icon: "🌍" },
    { label: "Growth", value: analytics.growth, icon: "📊" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {stats.map((stat) => (
        <div key={stat.label} className="rounded-2xl border-2 border-white bg-white/80 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[14px]">{stat.icon}</span>
          </div>
          <p className="mt-1.5 text-[16px] font-bold text-ink">{stat.value}</p>
          <p className="text-[10px] text-ink/40">{stat.label}</p>
        </div>
      ))}
    </div>
  );
}
