"use client";

const limits = [
  { label: "Tokens Used", used: 145200, total: 500000, unit: "tokens", color: "from-deep-violet to-magenta" },
  { label: "Databanks", used: 3, total: 10, unit: "databanks", color: "from-magenta to-coral" },
  { label: "Platforms Connected", used: 4, total: 7, unit: "platforms", color: "from-sky-400 to-blue-500" },
  { label: "AI Agents", used: 2, total: 5, unit: "agents", color: "from-emerald-400 to-emerald-600" },
];

export default function ProfileLimits() {
  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-5">
      <h2 className="text-[14px] font-bold text-ink mb-4">Usage Limits</h2>
      <div className="space-y-4">
        {limits.map((limit) => {
          const percentage = (limit.used / limit.total) * 100;
          return (
            <div key={limit.label}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-[11px] font-semibold text-ink">{limit.label}</span>
                <span className="text-[10px] text-ink/40">
                  {limit.used.toLocaleString()} / {limit.total.toLocaleString()} {limit.unit}
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-ink/[0.06]">
                <div
                  className={`h-full rounded-full bg-gradient-to-r ${limit.color} transition-all duration-500`}
                  style={{ width: `${Math.min(percentage, 100)}%` }}
                />
              </div>
              <p className="mt-1 text-[9px] text-ink/30">{Math.round(percentage)}% used</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
