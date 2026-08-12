"use client";

const stats = [
  { label: "Total Videos", value: "55", icon: "🎬" },
  { label: "Total Views", value: "289.6K", icon: "👁️" },
  { label: "Avg Engagement", value: "10.8%", icon: "📈" },
  { label: "Platforms", value: "6", icon: "🌐" },
];

export default function StatsRow() {
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {stats.map((stat) => (
        <div key={stat.label} className="rounded-2xl border-2 border-white bg-white/80 p-4">
          <div className="flex items-center justify-between">
            <span className="text-[18px]">{stat.icon}</span>
            <span className="text-[11px] font-medium text-ink/40">{stat.label}</span>
          </div>
          <p className="mt-2 text-[20px] font-bold text-ink">{stat.value}</p>
        </div>
      ))}
    </div>
  );
}
