"use client";

import { useEffect, useMemo, useState } from "react";
import { GREETINGS, shuffled, timeGreeting } from "@/lib/greetings";

const TYPE_MS = 55;
const TYPE_JITTER_MS = 65;
const DELETE_MS = 28;
const HOLD_MS = 2500;
const START_DELAY_MS = 500;
const NEXT_DELAY_MS = 400;

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Animated dashboard greeting: types each salutation letter by letter,
 * holds it for 2.5s, deletes it, and moves to the next one.
 * Starts with the time-aware greeting, then cycles a shuffled pool.
 */
export default function Greeting({ name }: { name: string }) {
  const words = useMemo(() => [timeGreeting(), ...shuffled(GREETINGS)], []);
  const [reduced] = useState(prefersReducedMotion);
  const staticLine = `${words[0]}, ${name || "there"}`;
  const [display, setDisplay] = useState(() => (prefersReducedMotion() ? staticLine : ""));

  useEffect(() => {
    if (prefersReducedMotion()) return;
    let wordIndex = 0;
    let charIndex = 0;
    let deleting = false;
    let timer: ReturnType<typeof setTimeout>;
    let alive = true;

    const tick = () => {
      if (!alive) return;
      const full = `${words[wordIndex]}, ${name || "there"}`;
      if (!deleting) {
        charIndex += 1;
        setDisplay(full.slice(0, charIndex));
        if (charIndex === full.length) {
          deleting = true;
          timer = setTimeout(tick, HOLD_MS);
          return;
        }
        timer = setTimeout(tick, TYPE_MS + Math.random() * TYPE_JITTER_MS);
      } else {
        charIndex -= 1;
        setDisplay(full.slice(0, charIndex));
        if (charIndex === 0) {
          deleting = false;
          wordIndex = (wordIndex + 1) % words.length;
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
  }, [words, name]);

  return (
    <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">
      <span aria-hidden>
        {display}
        {!reduced && <LogoTailCursor />}
      </span>
      <span className="sr-only">{staticLine}. Animated greeting.</span>
    </h1>
  );
}

/**
 * The tail of the Sayvors mark (the two signal arcs trailing the ring),
 * used as the typing cursor. Arcs radiate in sequence like a live signal.
 */
function LogoTailCursor() {
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
