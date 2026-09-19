/* Shared notification helpers: pill kinds + fire-and-forget emitter.
   Only two events ever surface as reminder pills — everything else
   lives quietly in the bell and the detail page. */

export type PillKind = "pulled" | "failed";

export const PILL_META: Record<PillKind, { glow: string; badge: string; icon: string; label: string }> = {
  pulled: {
    glow: "shadow-[0_10px_36px_rgba(16,185,129,0.45)]",
    badge: "bg-gradient-to-br from-emerald-400 to-emerald-600",
    icon: "★",
    label: "New review",
  },
  failed: {
    glow: "shadow-[0_10px_36px_rgba(244,63,94,0.45)]",
    badge: "bg-gradient-to-br from-rose-400 to-red-600",
    icon: "!",
    label: "Reply failed",
  },
};

export interface PillData {
  id: string;
  kind: PillKind;
  text: string;
}

type PillListener = (pill: PillData) => void;

const listeners = new Set<PillListener>();
let seq = 0;

/** Fire a reminder pill from anywhere (no React context needed). */
export function notifyPill(text: string, kind: PillKind): void {
  seq += 1;
  const pill: PillData = { id: `${Date.now()}-${seq}`, kind, text };
  listeners.forEach((fn) => {
    try {
      fn(pill);
    } catch {
      /* a broken listener must never break the caller */
    }
  });
}

export function subscribePills(fn: PillListener): () => void {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}

const SEEN_KEY = "sayvors.notif.seen";
const SEEN_CAP = 60;

/** IDs already shown as pills (persisted so reloads don't replay). */
export function loadSeenIds(): Set<string> {
  try {
    const raw = window.localStorage.getItem(SEEN_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as unknown;
    return new Set(Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

export function rememberSeenIds(ids: Set<string>): void {
  try {
    window.localStorage.setItem(SEEN_KEY, JSON.stringify([...ids].slice(-SEEN_CAP)));
  } catch {
    /* private mode */
  }
}

/** Backend notification type -> pill kind (only these two surface). */
export function pillKindFor(type: string): PillKind | null {
  if (type === "review_pulled") return "pulled";
  if (type === "reply_failed") return "failed";
  return null;
}
