"use client";

import { useMemo } from "react";
import Typewriter from "@/components/Typewriter";
import { GREETINGS, shuffled, timeGreeting } from "@/lib/greetings";

/**
 * Animated dashboard greeting: cycles "<salutation>, <name>" with a
 * typewriter effect. Starts time-aware, then runs a shuffled pool.
 */
export default function Greeting({ name }: { name: string }) {
  const displayName = name || "there";
  const phrases = useMemo(
    () => [timeGreeting(), ...shuffled(GREETINGS)].map((w) => `${w}, ${displayName}`),
    [displayName]
  );

  return (
    <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">
      <Typewriter phrases={phrases} label={`${phrases[0]}. Animated greeting.`} />
    </h1>
  );
}
