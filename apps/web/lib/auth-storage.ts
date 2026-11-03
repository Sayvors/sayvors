/**
 * App-owned localStorage that belongs to the signed-in user.
 *
 * Chat transcripts contain business Q&A, contact groups contain customer
 * contact data, and verification_token was a legacy raw email token. None of
 * these may survive logout on a shared machine. Theme/locale preferences are
 * intentionally not in this list.
 */
export const SESSION_LOCAL_KEYS = [
  "verification_token",
  "sayvors.chat.open",
  "sayvors.chat.sessions",
  "sayvors.chat.active",
  "sayvors.chat.messages",
  "sayvors.contactGroups",
  "sayvors.notif.seen",
] as const;

export function clearSessionLocalState(): void {
  if (typeof window === "undefined") return;
  try {
    for (const key of SESSION_LOCAL_KEYS) {
      window.localStorage.removeItem(key);
    }
  } catch {
    /* storage unavailable — the server-side session is already gone */
  }
}
