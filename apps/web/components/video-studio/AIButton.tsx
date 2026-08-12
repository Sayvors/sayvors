"use client";

import Image from "next/image";

interface AIButtonProps {
  onClick: () => void;
  loading?: boolean;
  label?: string;
}

export default function AIButton({ onClick, loading = false, label = "Refine with AI" }: AIButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-deep-violet to-magenta px-3 py-1.5 text-[11px] font-bold text-white shadow-sm transition hover:shadow-md active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <Image src="/Sayvors_Icon.png" alt="" width={14} height={14} className="h-3.5 w-auto brightness-0 invert" />
      {loading ? (
        <span className="flex items-center gap-1">
          <span className="h-1 w-1 animate-pulse rounded-full bg-white" />
          Generating...
        </span>
      ) : (
        label
      )}
    </button>
  );
}
