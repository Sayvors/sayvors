"use client";

import { useMemo } from "react";
import Typewriter from "@/components/Typewriter";
import { AR_GREETINGS, GREETINGS, shuffled, timeGreeting } from "@/lib/greetings";
import { useI18n } from "@/lib/i18n/I18nProvider";

/**
 * Animated dashboard greeting: cycles "<salutation>, <name>" with a
 * typewriter effect. Starts time-aware, then runs a shuffled pool
 * in the active locale.
 */
export default function Greeting({ name }: { name: string }) {
  const { locale, t } = useI18n();
  const displayName = name || t.dashboard.greetingFallback;
  const pool = locale === "ar" ? AR_GREETINGS : GREETINGS;
  const phrases = useMemo(
    () => [timeGreeting(new Date(), locale), ...shuffled(pool)].map((w) => `${w}, ${displayName}`),
    [displayName, locale, pool]
  );

  return (
    <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">
      <Typewriter phrases={phrases} label={`${phrases[0]}. Animated greeting.`} />
    </h1>
  );
}
