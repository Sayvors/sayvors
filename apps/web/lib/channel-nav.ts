// Conditional Channels nav — shows only connected providers.
// Inbox is always first when anything is connected (unified triage).
// Overview (health grid / connect more) is always last.

export type ChannelNavRow = {
  key: "inbox" | "whatsapp" | "instagram" | "facebook" | "overview" | "connect";
  status?: "live" | "needs_fix" | "off";
  unread?: number;
};

const KNOWN_ORDER = ["whatsapp", "instagram", "facebook"] as const;

export function visibleChannelNav(
  channels: { platform: string }[],
  meta: { provider: string; status: string }[]
): ChannelNavRow[] {
  const live = new Set<string>();
  for (const c of channels) {
    if (typeof c.platform === "string") live.add(c.platform);
  }
  for (const m of meta) {
    if (m.status !== "revoked" && typeof m.provider === "string") live.add(m.provider);
  }
  const known = KNOWN_ORDER.filter((p) => live.has(p));
  if (known.length === 0) return [{ key: "connect" }];
  return [
    { key: "inbox" },
    ...known.map((k) => ({ key: k as ChannelNavRow["key"] })),
    { key: "overview" },
  ];
}
