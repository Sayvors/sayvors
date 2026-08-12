"use client";

import type { Video } from "./platforms";

interface VideoMetricsProps {
  video: Video;
}

export default function VideoMetrics({ video }: VideoMetricsProps) {
  const metrics = [
    { label: "Views", value: video.views, icon: "👁️", change: "+12%" },
    { label: "Likes", value: video.likes, icon: "❤️", change: "+8%" },
    { label: "Comments", value: video.comments, icon: "💬", change: "+5%" },
    { label: "Shares", value: video.shares, icon: "🔗", change: "+15%" },
    { label: "Watch Time", value: video.watchTime, icon: "⏱️", change: "+3%" },
    { label: "Retention", value: video.retention, icon: "📊", change: "+2%" },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
      {metrics.map((metric) => (
        <div key={metric.label} className="rounded-2xl border-2 border-white bg-white/80 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[14px]">{metric.icon}</span>
            <span className="text-[9px] font-semibold text-emerald-600 bg-emerald-50 px-1.5 py-0.5 rounded-full">{metric.change}</span>
          </div>
          <p className="mt-1.5 text-[16px] font-bold text-ink">{metric.value}</p>
          <p className="text-[10px] text-ink/40">{metric.label}</p>
        </div>
      ))}
    </div>
  );
}
