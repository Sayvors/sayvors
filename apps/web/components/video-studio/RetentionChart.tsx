"use client";

const retentionData = [
  { second: "0:00", percentage: 100 },
  { second: "0:05", percentage: 95 },
  { second: "0:10", percentage: 88 },
  { second: "0:15", percentage: 82 },
  { second: "0:20", percentage: 75 },
  { second: "0:25", percentage: 68 },
  { second: "0:30", percentage: 62 },
  { second: "0:35", percentage: 58 },
  { second: "0:40", percentage: 55 },
  { second: "0:45", percentage: 52 },
  { second: "0:50", percentage: 48 },
  { second: "0:55", percentage: 45 },
  { second: "1:00", percentage: 42 },
];

export default function RetentionChart() {
  const maxVal = 100;

  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
      <h3 className="text-[12px] font-bold text-ink mb-3">Audience Retention</h3>
      <div className="relative h-40">
        <svg className="h-full w-full" viewBox="0 0 400 120" preserveAspectRatio="none">
          {/* Grid lines */}
          {[0, 25, 50, 75, 100].map((v) => (
            <line key={v} x1="0" y1={120 - (v / maxVal) * 120} x2="400" y2={120 - (v / maxVal) * 120} stroke="#f3f4f6" strokeWidth="1" />
          ))}
          {/* Area */}
          <path
            d={`M0,${120 - (retentionData[0].percentage / maxVal) * 120} ${retentionData.map((d, i) => `L${(i / (retentionData.length - 1)) * 400},${120 - (d.percentage / maxVal) * 120}`).join(" ")} L400,120 L0,120 Z`}
            fill="url(#retentionGradient)"
          />
          {/* Line */}
          <path
            d={`M0,${120 - (retentionData[0].percentage / maxVal) * 120} ${retentionData.map((d, i) => `L${(i / (retentionData.length - 1)) * 400},${120 - (d.percentage / maxVal) * 120}`).join(" ")}`}
            fill="none"
            stroke="#3d1d6e"
            strokeWidth="2"
          />
          <defs>
            <linearGradient id="retentionGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3d1d6e" stopOpacity="0.2" />
              <stop offset="100%" stopColor="#3d1d6e" stopOpacity="0" />
            </linearGradient>
          </defs>
        </svg>
      </div>
      <div className="flex justify-between mt-2">
        <span className="text-[9px] text-ink/30">0:00</span>
        <span className="text-[9px] text-ink/30">0:30</span>
        <span className="text-[9px] text-ink/30">1:00</span>
      </div>
    </div>
  );
}
