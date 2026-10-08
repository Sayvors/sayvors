"use client";

/*
 * Shared primitives for the Instagram hub — one home so the grid, the post
 * viewer and the stories row never drift apart.
 */

export const INK = "text-[var(--ui-ink)]";
export const INK2 = "text-[var(--ui-ink-2)]";

/** Instagram-style compact age: 5m · 3h · 2d · 6w · 1y. */
export function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const s = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return "now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d}d`;
  const w = Math.floor(d / 7);
  if (w < 52) return `${w}w`;
  return `${Math.floor(w / 52)}y`;
}

/** Initial-in-a-circle, the stand-in for avatars the API never gives us. */
export function Avatar({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)] text-[12px] font-bold text-[var(--ui-ink)]"
    >
      {name.charAt(0).toUpperCase()}
    </span>
  );
}

export function Icon({
  path,
  className,
}: {
  path: string;
  className: string;
}) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} fill="currentColor">
      <path d={path} />
    </svg>
  );
}

export const HEART_PATH =
  "M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z";
export const BUBBLE_PATH =
  "M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z";

export const HeartIcon = ({ className }: { className: string }) => (
  <Icon path={HEART_PATH} className={className} />
);

export const BubbleIcon = ({ className }: { className: string }) => (
  <Icon path={BUBBLE_PATH} className={className} />
);
