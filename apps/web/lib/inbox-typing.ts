"use client";

/**
 * Per-thread "someone is typing" state for the inbox.
 *
 * Two independent signals feed one flag per thread:
 *
 *   - `ai`      — server-pushed. The consumer publishes typing:true when it
 *                 starts generating a reply and typing:false when it lands.
 *                 Authoritative, but only as reliable as the connection.
 *   - `customer`— inferred locally. Meta sends no typing webhook to business
 *                 apps, so the only observable proxy is "an inbound message
 *                 arrived and nothing outbound has followed yet". Cheap, and
 *                 wrong whenever the AI deliberately does not reply (non-text
 *                 messages, deselected assets, stale events) or a human agent
 *                 simply has not answered yet. Treated as a hint and given a
 *                 short expiry for exactly that reason.
 *
 * Every flag auto-expires. A typing indicator is ephemeral state; anything
 * that can strand it on screen (crashed worker, dropped "stop typing"
 * frame) should heal itself rather than need a reconciliation pass.
 */

import { useSyncExternalStore } from "react";

export type TypingSource = "ai" | "customer";

/** AI signals arrive over the socket; the customer hint is local and short. */
const EXPIRY_MS: Record<TypingSource, number> = {
  // Generous: a reply is classify + generate + optional split, several
  // seconds. Refreshed by each typing:true while work continues.
  ai: 30_000,
  // The customer hint is a guess, so it clears quickly. Anything longer reads
  // as "this customer is stuck" when it is really "nobody has replied yet".
  customer: 4_000,
};

type Entry = { source: TypingSource; expiresAt: number };

const entries = new Map<string, Entry>();
let sweepTimer: ReturnType<typeof setInterval> | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const l of listeners) l();
}

function sweep(): void {
  const now = Date.now();
  let changed = false;
  for (const [key, entry] of entries) {
    if (entry.expiresAt <= now) {
      entries.delete(key);
      changed = true;
    }
  }
  if (changed) emit();
  // Stop the timer once nothing is pending rather than polling forever.
  if (entries.size === 0 && sweepTimer !== null) {
    clearInterval(sweepTimer);
    sweepTimer = null;
  }
}

function ensureSweeper(): void {
  if (sweepTimer === null) {
    sweepTimer = setInterval(sweep, 1_000);
  }
}

/** Build the composite key the inbox uses for a thread. */
export function typingKey(
  channelId?: string | null,
  contactId?: string | null,
): string {
  return `${channelId ?? ""}:${contactId ?? ""}`;
}

function set(key: string, source: TypingSource, active: boolean): void {
  if (!key.startsWith(":") && key === ":") return; // no channel id
  if (active) {
    entries.set(key, { source, expiresAt: Date.now() + EXPIRY_MS[source] });
    ensureSweeper();
  } else {
    entries.delete(key);
  }
  emit();
}

/** Server-pushed AI signal. */
export function setAiTyping(
  channelId: string | undefined,
  contactId: string | null | undefined,
  active: boolean,
): void {
  set(typingKey(channelId, contactId), "ai", active);
}

/**
 * Local hint: a message arrived and we are waiting to see a reply. Always
 * short-lived — see the note on the customer branch above.
 */
export function setCustomerAwaiting(
  channelId: string | undefined,
  contactId: string | null | undefined,
): void {
  set(typingKey(channelId, contactId), "customer", true);
}

/** Any outbound message means the reply landed; clear both signals. */
export function clearThreadTyping(
  channelId: string | undefined,
  contactId: string | null | undefined,
): void {
  entries.delete(typingKey(channelId, contactId));
  emit();
}

/** Non-reactive read, for use inside realtime handlers. */
export function getTypingSource(
  channelId: string | undefined,
  contactId: string | null | undefined,
): TypingSource | null {
  const entry = entries.get(typingKey(channelId, contactId));
  if (!entry) return null;
  return entry.expiresAt <= Date.now() ? null : entry.source;
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

const EMPTY: TypingSource | null = null;

/** Reactive read for components. */
export function useTypingSource(
  channelId: string | undefined,
  contactId: string | null | undefined,
): TypingSource | null {
  return useSyncExternalStore(
    subscribe,
    () => getTypingSource(channelId, contactId),
    () => EMPTY,
  );
}
