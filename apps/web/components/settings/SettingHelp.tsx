"use client";

import { useEffect, useRef, useState, useId } from "react";
import Mascot, { type MascotHandle } from "@/components/Mascot";

export type SettingHelpProps = {
  /** Accessible label for the trigger button. */
  ariaLabel: string;
  /** Bold title shown at the top of the bubble. */
  title?: string;
  /** Scenario phrases cycled by the typewriter inside the bubble. */
  phrases: string[];
  /** Mascot size in px. */
  size?: number;
};

/**
 * Group-level "explain this setting" widget for settings pages.
 *
 * A small help trigger opens an inline mascot + message-cloud bubble that
 * types out the group's scenarios one at a time, looping until closed.
 *
 * Why a mascot rather than a tooltip: the point of this is a scenario -- what
 * actually happens to a lead when you change this number -- and a tooltip is
 * dismissed by accident and cannot be read at a comfortable pace. A bubble
 * that stays open, types itself out, and can be replayed is a thing you read
 * with a cup of tea, not a thing you fight.
 *
 * Accessibility, since a decorative mascot is exactly where these go wrong:
 *   - the trigger is a real button with an aria-label and aria-expanded
 *   - the bubble is a live region, so a screen reader hears each phrase as it
 *     is revealed rather than silently swapping text under the user
 *   - Escape closes it, focus returns to the trigger
 *   - prefers-reduced-motion skips the typewriter and prints the whole phrase
 *
 * The Mascot itself already handles pointer tracking, reduced motion, and its
 * own focus outline, so none of that is duplicated here.
 */

const TYPE_MS = 26; // per character
const HOLD_MS = 3400; // a finished phrase rests before the next one
const ERASE_MS = 12; // per character

export default function SettingHelp({
  ariaLabel,
  title,
  phrases,
  size = 72,
}: SettingHelpProps) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [done, setDone] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const mascot = useRef<MascotHandle>(null);
  const bodyId = useId();

  // Nothing to type when there are no phrases; the trigger would only open an
  // empty box.
  if (!phrases.length) return null;

  // Closing must leave the caret where the user can find it again.
  useEffect(() => {
    if (!open) triggerRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) {
      setText("");
      setDone(false);
      return;
    }

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      // Still cycles, so the button does something -- it just stops animating.
      let i = 0;
      setText(phrases[i]);
      setDone(true);
      const hold = window.setInterval(() => {
        i = (i + 1) % phrases.length;
        setText(phrases[i]);
        mascot.current?.play(i === 0 ? "delighted" : "sparkle");
      }, HOLD_MS);
      return () => window.clearInterval(hold);
    }

    let phrase = 0;
    let char = 0;
    let erasing = false;
    let timer = 0;

    const tick = () => {
      const current = phrases[phrase];
      char += erasing ? -1 : 1;

      if (!erasing && char >= current.length) {
        erasing = true;
        char = current.length;
        setDone(true);
        mascot.current?.play("delighted");
        timer = window.setTimeout(tick, HOLD_MS);
        return;
      }

      if (erasing && char <= 0) {
        erasing = false;
        char = 0;
        phrase = (phrase + 1) % phrases.length;
        setDone(false);
        mascot.current?.play("sparkle");
        timer = window.setTimeout(tick, TYPE_MS * 2);
        return;
      }

      setDone(false);
      setText(current.slice(0, char));
      timer = window.setTimeout(tick, erasing ? ERASE_MS : TYPE_MS);
    };

    timer = window.setTimeout(tick, TYPE_MS);
    return () => window.clearTimeout(timer);
  }, [open, phrases]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="flex flex-col items-end gap-2">
      <button
        ref={triggerRef}
        type="button"
        aria-label={ariaLabel}
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="flex h-6 w-6 items-center justify-center rounded-full border border-ink/10 bg-white text-[13px] font-bold text-ink/50 transition hover:bg-ink/[0.04] hover:text-ink focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet active:translate-y-[2px] active:scale-[0.98] dark:border-fog/10 dark:bg-ink dark:text-fog/50 dark:hover:bg-fog/[0.08] dark:hover:text-fog dark:focus-visible:outline-fog"
      >
        <span aria-hidden>?</span>
      </button>

      {open && (
        <div
          ref={bubbleRef}
          className="flex items-end gap-2"
          style={{ maxWidth: size * 4.2 }}
        >
          <div
            id={bodyId}
            role="status"
            aria-live="polite"
            className="min-w-0 rounded-[16px] border border-ink/[0.08] bg-white px-3 py-2 shadow-[0_1px_0_0_rgba(255,255,255,0.9)_inset,0_2px_10px_rgba(20,16,31,0.10)] dark:border-fog/[0.08] dark:bg-ink dark:shadow-[0_1px_0_0_rgba(255,255,255,0.06)_inset,0_2px_10px_rgba(0,0,0,0.4)]"
          >
            {title && (
              <p className="mb-1 text-[11px] font-bold text-ink dark:text-fog">{title}</p>
            )}
            <p className="text-[12px] leading-relaxed text-ink/70 dark:text-fog/70">
              {text}
              {/* The caret is decorative; the live region already announced
                  the text, so it stays out of the accessibility tree. */}
              {!done && <span aria-hidden className="ml-0.5">|</span>}
            </p>
          </div>

          <Mascot ref={mascot} size={size} label="Sayvors Mascot" className="shrink-0" />
        </div>
      )}
    </div>
  );
}