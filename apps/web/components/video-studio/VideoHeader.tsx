"use client";

interface VideoHeaderProps {
  title: string;
  publishedAt: string;
  status: string;
  color: string;
}

export default function VideoHeader({ title, publishedAt, status, color }: VideoHeaderProps) {
  return (
    <div className="flex items-start gap-4">
      <div
        className="h-16 w-28 shrink-0 rounded-xl flex items-center justify-center"
        style={{ backgroundColor: color + "15" }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-6 w-6" style={{ color }}>
          <polygon points="5 3 19 12 5 21 5 3" fill="currentColor" opacity="0.5" />
        </svg>
      </div>
      <div className="flex-1">
        <h1 className="text-[18px] sm:text-[20px] font-bold text-ink">{title}</h1>
        <p className="mt-0.5 text-[12px] text-ink/45">
          {publishedAt} · <span className={`font-semibold ${status === "published" ? "text-emerald-600" : "text-amber-600"}`}>{status}</span>
        </p>
      </div>
    </div>
  );
}
