"use client";

import { useId } from "react";

type LogoLoaderProps = {
  /** Height of the mark in px (width scales automatically). */
  size?: number;
  /** Accessible label + optional visible caption under the mark. */
  label?: string;
  /** Show the caption text under the mark. */
  showText?: boolean;
  /** Render as a full-screen overlay instead of inline. */
  overlay?: boolean;
  className?: string;
};

/**
 * Brand loader: the Sayvors mark (gradient ring + signal tail) with
 * radiating waves and a slow orbiting dash ring.
 *
 * Usage — inline (data fetching inside a card):
 *   <LogoLoader size={36} label="Loading analytics…" showText />
 *
 * Usage — full page / route transition:
 *   <LogoLoader overlay label="Loading dashboard…" />
 */
export default function LogoLoader({
  size = 44,
  label = "Loading",
  showText = false,
  overlay = false,
  className = "",
}: LogoLoaderProps) {
  const gradientId = useId();

  const mark = (
    <span role="status" aria-label={label} className={`relative inline-flex ${className}`}>
      <svg
        height={size}
        viewBox="0 0 26 20"
        aria-hidden
        className="h-auto w-auto"
        style={{ height: size }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#8b5cf6" />
            <stop offset="55%" stopColor="#d946a8" />
            <stop offset="100%" stopColor="#ff4f6e" />
          </linearGradient>
        </defs>
        {/* Ring */}
        <circle
          cx="8"
          cy="10"
          r="6.5"
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth="3"
        />
        {/* Signal tail */}
        <path
          d="M18 5.5 Q22 10 18 14.5"
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth="2.6"
          strokeLinecap="round"
          className="animate-signal"
        />
        <path
          d="M21 3 Q27 10 21 17"
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth="2.6"
          strokeLinecap="round"
          className="animate-signal-delay"
        />
      </svg>
    </span>
  );

  if (!overlay) {
    if (!showText) return mark;
    return (
      <span className={`inline-flex flex-col items-center gap-2 ${className}`}>
        {mark}
        <span className="animate-pulse text-[12px] font-medium text-ink/45">{label}</span>
      </span>
    );
  }

  return (
    <div
      role="status"
      aria-label={label}
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-3 bg-background/80 backdrop-blur-sm"
    >
      {mark}
      <p className="animate-pulse text-[13px] font-medium text-ink/55">{label}</p>
    </div>
  );
}
