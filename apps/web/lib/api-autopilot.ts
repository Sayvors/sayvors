"use client";

import { apiFetch } from "./api-rag";

export type PilotState = "on" | "off" | "mixed" | "none";

export interface PilotChannel {
  id: string;
  display_name: string | null;
  enabled: boolean;
  approval_mode: string;
}

/**
 * Auto Pilot is a global switch over every connected Google channel:
 * - ON  = all channels enabled + approval_mode "auto"
 *         (AI answers instantly, no approval step)
 * - OFF = all channels enabled + approval_mode "approval"
 *         (every reply waits in the approval queue)
 * Per-channel fine-tuning stays on the Automations page.
 */
export async function fetchPilotChannels(): Promise<PilotChannel[]> {
  const data = await apiFetch("/api/v1/channels/?limit=100");
  const google: { id: string; display_name: string | null; platform: string }[] = (
    data.channels ?? []
  ).filter((c: { platform: string }) => c.platform === "google_reviews");

  return Promise.all(
    google.map(async (c) => {
      try {
        const cfg = await apiFetch(`/api/v1/channels/${c.id}/autoreply`);
        return {
          id: c.id,
          display_name: c.display_name,
          enabled: !!cfg.enabled,
          approval_mode: cfg.approval_mode ?? "auto",
        };
      } catch {
        return { id: c.id, display_name: c.display_name, enabled: false, approval_mode: "auto" };
      }
    })
  );
}

export function derivePilotState(channels: PilotChannel[]): PilotState {
  if (channels.length === 0) return "none";
  const on = channels.filter((c) => c.enabled && c.approval_mode !== "approval").length;
  if (on === channels.length) return "on";
  if (on === 0) return "off";
  return "mixed";
}

export async function setPilot(on: boolean, channels: PilotChannel[]): Promise<void> {
  await Promise.all(
    channels.map((c) =>
      apiFetch(`/api/v1/channels/${c.id}/autoreply`, {
        method: "PUT",
        body: JSON.stringify({
          enabled: true,
          approval_mode: on ? "auto" : "approval",
        }),
      })
    )
  );
}
