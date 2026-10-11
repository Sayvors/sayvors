"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";

export interface ChannelOption {
  id: string;
  label: string;
}

export function useGoogleChannels() {
  const [channels, setChannels] = useState<ChannelOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/v1/channels")
      .then((data) => {
        if (cancelled) return;
        const google = (data.channels ?? [])
          .filter((c: { platform: string }) => c.platform === "google_reviews")
          .map((c: { id: string; display_name: string | null }) => ({
            id: c.id,
            label: c.display_name ?? "Google Business",
          }));
        setChannels(google);
      })
      .catch(() => {
        if (!cancelled) setChannels([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return channels;
}

export const RANGES = [7, 30, 90] as const;

export function RangeChannelControls({
  days,
  setDays,
  channelId,
  setChannelId,
  channels,
}: {
  days: number;
  setDays: (d: number) => void;
  channelId: string | null;
  setChannelId: (c: string | null) => void;
  channels: ChannelOption[];
}) {
  const rangeBtn = (active: boolean) =>
    `rounded-[2px] px-2.5 py-1 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
      active ? "border border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink)]" : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
    }`;
  return (
    <div className="flex items-center gap-2">
      {channels.length > 1 && (
        <select
          value={channelId ?? ""}
          onChange={(e) => setChannelId(e.target.value || null)}
          aria-label="Filter by location"
          className="ui-input h-8 bg-[var(--ui-surface)] px-2 text-[12px] text-[var(--ui-ink)] transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        >
          <option value="">All locations</option>
          {channels.map((c) => (
            <option key={c.id} value={c.id}>{c.label}</option>
          ))}
        </select>
      )}
      <div className="flex rounded-[2px] bg-[var(--ui-sunken)] p-0.5" role="group" aria-label="Time range">
        {RANGES.map((r) => (
          <button key={r} onClick={() => setDays(r)} aria-pressed={days === r} className={rangeBtn(days === r)}>
            {r}d
          </button>
        ))}
      </div>
    </div>
  );
}
