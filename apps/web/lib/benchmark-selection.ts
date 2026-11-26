import { subjectKey } from "@/lib/api-benchmark";

export interface CompareChannelOption {
  id: string;
  display_name: string | null;
  platform: string;
  status: string;
  verification_status: string | null;
  verified: boolean;
}

/** Verified branches lead the picker; API creation order is only a tie-breaker. */
export function sortCompareChannels(channels: CompareChannelOption[]): CompareChannelOption[] {
  return [...channels].sort((a, b) =>
    Number(b.verified) - Number(a.verified)
    || (a.display_name ?? "").localeCompare(b.display_name ?? ""),
  );
}

/** A bare Compare URL must never silently select an unverified branch. */
export function defaultCompareMain(channels: CompareChannelOption[]): string | null {
  const firstVerified = channels.find((channel) => channel.verified);
  return firstVerified ? subjectKey("own", firstVerified.id) : null;
}
