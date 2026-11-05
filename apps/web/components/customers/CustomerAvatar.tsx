"use client";

import { useState } from "react";

/** Two-letter fallback: "Hamza Shah" → "HS", "saeed" → "SA". */
export function initialsFor(name: string | null | undefined): string {
  const base = (name || "?").trim();
  const parts = base.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return base.slice(0, 2).toUpperCase();
}

const SIZES = {
  sm: "h-9 w-9 text-[11px]",
  md: "h-11 w-11 text-[13px]",
  lg: "h-16 w-16 text-[18px]",
} as const;

/**
 * Reviewer/contact photo with an initials fallback.
 *
 * Google and Meta CDN links expire, so a failed load must fall back to text
 * instead of a broken-image icon. Tracking the failed URL (not a boolean)
 * lets a refreshed URL recover on its own.
 */
export default function CustomerAvatar({
  name,
  url,
  size = "md",
  className = "",
}: {
  name: string | null | undefined;
  url?: string | null;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const show = !!url && failedUrl !== url;
  const box = `shrink-0 rounded-full bg-[var(--ui-sunken)] text-[var(--ui-ink)] ring-1 ring-[var(--ui-line)] ${SIZES[size]} ${className}`;

  if (show) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        key={url}
        src={url}
        alt=""
        onError={() => setFailedUrl(url)}
        className={`object-cover ${box}`}
      />
    );
  }

  return (
    <span aria-hidden className={`flex items-center justify-center font-bold ${box}`}>
      {initialsFor(name)}
    </span>
  );
}
