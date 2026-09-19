"use client";

interface DatabankStatsProps {
  totalDatabanks: number;
  totalDocs: number;
  totalSize: string;
  processedCount: number;
}

export default function DatabankStats({ totalDatabanks, totalDocs, totalSize, processedCount }: DatabankStatsProps) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
        <p className="text-[10px] text-ink/45">Databanks</p>
        <p className="text-[22px] font-bold text-ink">{totalDatabanks}</p>
      </div>
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
        <p className="text-[10px] text-ink/45">Documents</p>
        <p className="text-[22px] font-bold text-ink">{totalDocs}</p>
      </div>
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
        <p className="text-[10px] text-ink/45">Total Size</p>
        <p className="text-[22px] font-bold text-ink">{totalSize}</p>
      </div>
      <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
        <p className="text-[10px] text-ink/45">Processed</p>
        <p className="text-[22px] font-bold text-emerald-600">{processedCount}</p>
      </div>
    </div>
  );
}
