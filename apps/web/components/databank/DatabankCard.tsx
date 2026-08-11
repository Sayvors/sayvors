"use client";

interface DatabankCardProps {
  id: string;
  name: string;
  description?: string;
  accentColor?: string;
  docCount: number;
  totalSize: number;
  isSelected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  formatBytes: (bytes: number) => string;
}

export default function DatabankCard({
  name,
  description,
  accentColor,
  docCount,
  totalSize,
  isSelected,
  onSelect,
  onDelete,
  formatBytes,
}: DatabankCardProps) {
  return (
    <div
      onClick={onSelect}
      className={`cursor-pointer rounded-2xl border-2 bg-white/80 p-4 transition-all hover:shadow-md ${
        isSelected
          ? "border-deep-violet shadow-lg shadow-deep-violet/10"
          : "border-white hover:border-deep-violet/30"
      }`}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-white shadow-md"
          style={{ backgroundColor: accentColor || "#3d1d6e" }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
            <ellipse cx="12" cy="5" rx="9" ry="3" />
            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
          </svg>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[14px] font-bold text-ink truncate">{name}</p>
          <p className="text-[11px] text-ink/45">
            {docCount || 0} docs · {formatBytes(totalSize || 0)}
          </p>
          {description && (
            <p className="mt-1 text-[11px] text-ink/35 line-clamp-1">{description}</p>
          )}
        </div>
      </div>

      {isSelected && (
        <div className="mt-3 flex gap-2">
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="rounded-lg border-2 border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/50 transition hover:border-coral/30 hover:text-coral"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}
