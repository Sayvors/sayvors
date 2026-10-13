"use client";

import { useMemo } from "react";
import Typewriter from "@/components/Typewriter";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { TypingSource } from "@/lib/inbox-typing";

/*
 * Reuses the dashboard greeting scene (components/Typewriter.tsx) verbatim —
 * same Sayvors mark as the cursor, same reduced-motion handling — so typing
 * feels like the same product moment rather than a bolt-on.
 */

/** Short enough to read mid-type; these loop for as long as the state holds. */
const AI_PHRASES_EN = ["Composing", "Thinking", "Drafting", "On it"];
const AI_PHRASES_AR = ["يكتب", "يفكر", "يصيغ", "لحظة"];
const CUSTOMER_PHRASES_EN = ["Typing", "Writing"];
const CUSTOMER_PHRASES_AR = ["يكتب", "يكتبون"];

function poolFor(source: TypingSource, ar: boolean) {
  if (source === "customer") return ar ? CUSTOMER_PHRASES_AR : CUSTOMER_PHRASES_EN;
  return ar ? AI_PHRASES_AR : AI_PHRASES_EN;
}

/**
 * Animated "someone is typing" row for a conversation.
 *
 * `source` picks the voice: `ai` is Sayvors replying to the customer,
 * `customer` is our local hint that something came in and nothing has come
 * back. The caller is responsible for the lifetime of the row — see
 * lib/inbox-typing.ts, where every flag self-expires.
 */
export default function TypingIndicator({
  source,
  contactName,
}: {
  source: TypingSource;
  contactName?: string | null;
}) {
  const { locale } = useI18n();
  const isAr = locale === "ar";
  const phrases = useMemo(() => {
    const base = poolFor(source, isAr);
    // Append the name only for the AI voice: "Composing, Sara" reads as the
    // assistant working for that customer. The customer hint stays anonymous.
    const name = source === "ai" ? contactName : null;
    return name ? base.map((p) => `${p}, ${name}`) : base;
  }, [source, isAr, contactName]);

  const who = source === "ai" ? "Sayvors" : "The customer";

  return (
    <div className="mb-2 flex justify-start" role="status" aria-live="polite">
      <div className="flex items-center gap-2 rounded-2xl bg-ink/[0.05] px-3.5 py-2.5 text-[13px] text-ink dark:bg-fog/[0.08] dark:text-fog">
        <LogoMark />
        <Typewriter
          phrases={phrases}
          label={`${who} is typing`}
          holdMs={1800}
          className={isAr ? "text-right" : undefined}
        />
      </div>
    </div>
  );
}

/**
 * The Sayvors ring + signal arcs, sized as a leading avatar.
 *
 * Reuses LogoTailCursor's geometry but drops its em-relative trailing-cursor
 * sizing and the CSS pulse classes: as a leading mark it should sit still.
 */
function LogoMark() {
  return (
    <svg
      viewBox="0 0 26 20"
      aria-hidden
      className="h-4 w-auto shrink-0"
    >
      <defs>
        <linearGradient id="sayvors-typing-mark" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#8b5cf6" />
          <stop offset="55%" stopColor="#d946a8" />
          <stop offset="100%" stopColor="#ff4f6e" />
        </linearGradient>
      </defs>
      <circle cx="8" cy="10" r="6.5" fill="none" stroke="url(#sayvors-typing-mark)" strokeWidth="3" />
      <path d="M18 5.5 Q22 10 18 14.5" fill="none" stroke="url(#sayvors-typing-mark)" strokeWidth="2.6" strokeLinecap="round" className="animate-signal" />
      <path d="M21 3 Q27 10 21 17" fill="none" stroke="url(#sayvors-typing-mark)" strokeWidth="2.6" strokeLinecap="round" className="animate-signal-delay" />
    </svg>
  );
}
