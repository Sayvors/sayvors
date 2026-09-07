"use client";

import { Fragment, useEffect, useMemo, useState } from "react";

const TYPE_MS = 55;
const TYPE_JITTER_MS = 65;
const DELETE_MS = 28;
const START_DELAY_MS = 500;
const NEXT_DELAY_MS = 400;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function renderLines(display: string) {
  return display.split("\n").map((line, i, arr) => (
    <Fragment key={i}>
      {line}
      {i < arr.length - 1 && <br />}
    </Fragment>
  ));
}

/**
 * Generic typewriter: types each phrase letter by letter (`\n` = line break),
 * holds it, deletes it, and moves to the next one in a loop.
 * Trailing cursor is the tail of the Sayvors mark (ring + signal arcs).
 */
export default function Typewriter({
  phrases,
  label,
  holdMs = 2500,
  className,
}: {
  phrases: string[];
  label: string;
  holdMs?: number;
  className?: string;
}) {
  const list = useMemo(() => phrases.filter((p) => p.length > 0), [phrases]);
  const [reduced] = useState(prefersReducedMotion);
  const [display, setDisplay] = useState(() => (prefersReducedMotion() ? (list[0] ?? "") : ""));

  useEffect(() => {
    if (prefersReducedMotion() || list.length === 0) return;
    let phraseIndex = 0;
    let charIndex = 0;
    let deleting = false;
    let timer: ReturnType<typeof setTimeout>;
    let alive = true;

    const tick = () => {
      if (!alive) return;
      const full = list[phraseIndex];
      if (!deleting) {
        charIndex += 1;
        setDisplay(full.slice(0, charIndex));
        if (charIndex === full.length) {
          deleting = true;
          timer = setTimeout(tick, holdMs);
          return;
        }
        timer = setTimeout(tick, TYPE_MS + Math.random() * TYPE_JITTER_MS);
      } else {
        charIndex -= 1;
        setDisplay(full.slice(0, charIndex));
        if (charIndex === 0) {
          deleting = false;
          phraseIndex = (phraseIndex + 1) % list.length;
          timer = setTimeout(tick, NEXT_DELAY_MS);
          return;
        }
        timer = setTimeout(tick, DELETE_MS);
      }
    };

    timer = setTimeout(tick, START_DELAY_MS);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [list, holdMs]);

  return (
    <>
      <span aria-hidden className={className}>
        {renderLines(display)}
        {!reduced && <LogoTailCursor />}
      </span>
      <span className="sr-only">{label}</span>
    </>
  );
}

/**
 * The Sayvors mark (gradient ring + trailing signal arcs),
 * used as the typing cursor. Arcs radiate in sequence like a live signal.
 */
export function LogoTailCursor() {
  return (
    <svg
      viewBox="0 0 26 20"
      aria-hidden
      className="ml-1 inline-block h-[0.95em] w-auto align-[-0.12em]"
    >
      <defs>
        <linearGradient id="sayvors-tail" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#8b5cf6" />
          <stop offset="55%" stopColor="#d946a8" />
          <stop offset="100%" stopColor="#ff4f6e" />
        </linearGradient>
      </defs>
      <circle
        cx="8"
        cy="10"
        r="6.5"
        fill="none"
        stroke="url(#sayvors-tail)"
        strokeWidth="3"
      />
      <path
        d="M18 5.5 Q22 10 18 14.5"
        fill="none"
        stroke="url(#sayvors-tail)"
        strokeWidth="2.6"
        strokeLinecap="round"
        className="animate-signal"
      />
      <path
        d="M21 3 Q27 10 21 17"
        fill="none"
        stroke="url(#sayvors-tail)"
        strokeWidth="2.6"
        strokeLinecap="round"
        className="animate-signal-delay"
      />
    </svg>
  );
}
