"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";

interface AutoReplyToggleProps {
  onComplete: () => void;
}

interface Channel {
  id: string;
  platform: string;
  display_name: string | null;
  status: string;
}

interface AutoReplyConfig {
  channel_id: string;
  enabled: boolean;
  tone: string;
  databank_id: string | null;
  min_rating_auto: number;
  model: string;
}

const TONE_OPTIONS = [
  { value: "friendly", label: "Friendly", desc: "Warm and approachable" },
  { value: "professional", label: "Professional", desc: "Formal and polite" },
  { value: "apologetic", label: "Apologetic", desc: "Empathetic and calm" },
  { value: "playful", label: "Playful", desc: "Light and upbeat" },
];

const PLATFORM_LABEL: Record<string, string> = {
  google_reviews: "Google Reviews",
};

export default function AutoReplyToggle({ onComplete }: AutoReplyToggleProps) {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [configs, setConfigs] = useState<Record<string, AutoReplyConfig>>({});
  const [tone, setTone] = useState("friendly");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const list: Channel[] = (data.channels ?? []).filter(
          (c: Channel) => c.platform === "google_reviews" && c.status === "active"
        );
        if (cancelled) return;
        setChannels(list);

        // Load existing autoreply config per channel
        const configsByChannel: Record<string, AutoReplyConfig> = {};
        for (const ch of list) {
          try {
            const cfg = await apiFetch(`/api/v1/channels/${ch.id}/autoreply`);
            configsByChannel[ch.id] = cfg;
          } catch {
            // No config yet — keep defaults (enabled=false, tone="friendly")
          }
        }
        if (cancelled) return;
        setConfigs(configsByChannel);
        // Seed tone from the first existing config (if any)
        const firstCfg = Object.values(configsByChannel)[0];
        if (firstCfg?.tone) setTone(firstCfg.tone);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load channels");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const toggleChannel = (id: string) => {
    setConfigs((prev) => {
      const existing = prev[id];
      const enabled = !(existing?.enabled ?? false);
      return {
        ...prev,
        [id]: {
          channel_id: id,
          enabled,
          tone,
          databank_id: existing?.databank_id ?? null,
          min_rating_auto: existing?.min_rating_auto ?? 4,
          model: existing?.model ?? "openai:gpt-4o-mini",
        },
      };
    });
  };

  const handleSave = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      for (const ch of channels) {
        const cfg = configs[ch.id];
        if (!cfg) continue;
        await apiFetch(`/api/v1/channels/${ch.id}/autoreply`, {
          method: "PUT",
          body: JSON.stringify({ enabled: cfg.enabled, tone }),
        });
      }
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save auto-reply settings");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="py-8 text-center text-[13px] text-ink/40 dark:text-fog/40">
        Loading your channels…
      </div>
    );
  }

  if (channels.length === 0) {
    return (
      <div className="space-y-4 text-center">
        <p className="text-[14px] text-ink/60 dark:text-fog/60">
          You haven&apos;t connected any channels yet. Go back to the Connect step to link Google Reviews first.
        </p>
        <button
          onClick={onComplete}
          className="rounded-xl bg-deep-violet px-6 py-2.5 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90"
        >
          Got it
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <label className="block text-[13px] font-medium text-ink dark:text-fog">Channels to auto-reply on</label>
        <div className="mt-2 space-y-2">
          {channels.map((ch) => {
            const enabled = configs[ch.id]?.enabled ?? false;
            const label = ch.display_name || PLATFORM_LABEL[ch.platform] || ch.platform;
            return (
              <button
                key={ch.id}
                onClick={() => toggleChannel(ch.id)}
                className={`flex w-full items-center justify-between rounded-xl border px-4 py-3 text-left transition ${
                  enabled
                    ? "border-deep-violet/30 bg-deep-violet/5 dark:border-deep-violet/40"
                    : "border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink"
                }`}
              >
                <span className="text-[13px] font-medium text-ink dark:text-fog">{label}</span>
                <div className={`flex h-5 w-9 items-center rounded-full px-0.5 transition ${enabled ? "bg-deep-violet" : "bg-ink/20 dark:bg-fog/20"}`}>
                  <div className={`h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${enabled ? "translate-x-4" : "translate-x-0"}`} />
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <label className="block text-[13px] font-medium text-ink dark:text-fog">Reply tone</label>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {TONE_OPTIONS.map((t) => (
            <button
              key={t.value}
              onClick={() => setTone(t.value)}
              className={`rounded-xl border px-3 py-3 text-center transition ${
                tone === t.value
                  ? "border-deep-violet/30 bg-deep-violet/5 dark:border-deep-violet/40"
                  : "border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink"
              }`}
            >
              <p className="text-[12px] font-semibold text-ink dark:text-fog">{t.label}</p>
              <p className="text-[11px] text-ink/40 dark:text-fog/40 mt-0.5">{t.desc}</p>
            </button>
          ))}
        </div>
      </div>

      {error && <p className="text-[12px] text-red-600 dark:text-red-400">{error}</p>}

      <button
        onClick={handleSave}
        disabled={saving}
        className="rounded-xl bg-deep-violet px-6 py-2.5 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        {saving ? "Saving…" : "Save & Activate"}
      </button>
    </div>
  );
}
