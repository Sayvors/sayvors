/*
 * Which inbox thread the agent is reading right now, as the same
 * `${channel_id}:${key}` composite the InboxView uses. Module state, not
 * React state: the toast host must read it from inside its realtime
 * handler without becoming a re-render dependency of the inbox.
 */
let active = "";

export function setActiveThread(key: string | null): void {
  active = key ?? "";
}

export function isActiveThread(
  channelId?: string | null,
  contactId?: string | null,
): boolean {
  return Boolean(active) && active === `${channelId ?? ""}:${contactId ?? ""}`;
}
