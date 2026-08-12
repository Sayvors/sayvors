"use client";

const ageGroups = [
  { label: "13-17", percentage: 8 },
  { label: "18-24", percentage: 35 },
  { label: "25-34", percentage: 28 },
  { label: "35-44", percentage: 18 },
  { label: "45-54", percentage: 8 },
  { label: "55+", percentage: 3 },
];

const genderSplit = [
  { label: "Male", percentage: 58 },
  { label: "Female", percentage: 38 },
  { label: "Other", percentage: 4 },
];

export default function AudienceInsights() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* Age demographics */}
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
        <h3 className="text-[12px] font-bold text-ink mb-3">Age Demographics</h3>
        <div className="space-y-2">
          {ageGroups.map((group) => (
            <div key={group.label} className="flex items-center gap-3">
              <span className="text-[10px] font-medium text-ink/50 w-8 shrink-0">{group.label}</span>
              <div className="flex-1 h-2 rounded-full bg-ink/[0.06] overflow-hidden">
                <div
                  className="h-full rounded-full bg-deep-violet transition-all duration-500"
                  style={{ width: `${group.percentage}%` }}
                />
              </div>
              <span className="text-[10px] font-bold text-ink w-8 text-right">{group.percentage}%</span>
            </div>
          ))}
        </div>
      </div>

      {/* Gender split */}
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
        <h3 className="text-[12px] font-bold text-ink mb-3">Gender Split</h3>
        <div className="space-y-2">
          {genderSplit.map((group) => (
            <div key={group.label} className="flex items-center gap-3">
              <span className="text-[10px] font-medium text-ink/50 w-12 shrink-0">{group.label}</span>
              <div className="flex-1 h-2 rounded-full bg-ink/[0.06] overflow-hidden">
                <div
                  className="h-full rounded-full bg-magenta transition-all duration-500"
                  style={{ width: `${group.percentage}%` }}
                />
              </div>
              <span className="text-[10px] font-bold text-ink w-8 text-right">{group.percentage}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
