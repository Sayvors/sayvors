"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api-rag";
import { getAccessToken } from "@/lib/auth-context";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiChannel {
  id: string;
  platform: string;
  display_name: string | null;
  status: string;
  created_at: string;
}

interface AutoReply {
  channel_id: string;
  enabled: boolean;
  tone: string;
  databank_id: string | null;
  min_rating_auto: number;
  model: string;
}

const GOOGLE_ERRORS: Record<string, string> = {
  no_business_account: "No Google Business Profile was found on that Google account.",
  token_exchange_failed: "Google rejected the connection. Please try again.",
  invalid_state: "The connect session expired. Please click Connect again.",
  missing_code: "Google did not return an authorization code. Please try again.",
  access_denied: "You cancelled the Google consent screen.",
};

function ConnectHub() {
  const params = useSearchParams();
  const [channels, setChannels] = useState<ApiChannel[]>([]);
  const [autoreply, setAutoreply] = useState<Record<string, AutoReply>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const connectedCount = params.get("google_connected");
  const googleError = params.get("google_error");

  const load = useCallback(async () => {
    try {
      const data = await apiFetch("/api/v1/channels/?limit=100");
      setChannels(data.channels ?? []);
      const configs: Record<string, AutoReply> = {};
      await Promise.all(
        (data.channels ?? [])
          .filter((c: ApiChannel) => c.platform === "google_reviews")
          .map(async (c: ApiChannel) => {
            try {
              const cfg = await apiFetch(`/api/v1/channels/${c.id}/autoreply`);
              configs[c.id] = cfg;
            } catch {
              /* config endpoint creates default on first GET; ignore errors */
            }
          })
      );
      setAutoreply(configs);
    } catch {
      /* not logged in yet or backend down — cards still render */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    if (connectedCount !== null) {
      setBanner({
        kind: "ok",
        text: `Google Reviews connected! ${connectedCount} location(s) added.`,
      });
    } else if (googleError) {
      setBanner({
        kind: "err",
        text: GOOGLE_ERRORS[googleError] ?? `Google connect failed (${googleError}).`,
      });
    }
  }, [load, connectedCount, googleError]);

  const connectGoogle = () => {
    const token = getAccessToken();
    if (!token) {
      setBanner({ kind: "err", text: "Please log in first." });
      return;
    }
    window.location.href = `${API}/api/v1/channels/google/connect?token=${encodeURIComponent(token)}`;
  };

  const toggleAutoReply = async (channelId: string, enable: boolean) => {
    setBusy(channelId);
    try {
      const cfg = await apiFetch(`/api/v1/channels/${channelId}/autoreply`, {
        method: "PUT",
        body: JSON.stringify({ enabled: enable }),
      });
      setAutoreply((prev) => ({ ...prev, [channelId]: cfg }));
    } catch {
      setBanner({ kind: "err", text: "Could not save the auto-reply setting." });
    } finally {
      setBusy(null);
    }
  };

  const googleChannels = channels.filter((c) => c.platform === "google_reviews");

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div>
        <h1 className="text-[20px] font-bold text-ink dark:text-fog">Connect your channels</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
          Link your business accounts — our AI answers your customers there.
        </p>
      </div>

      {banner && (
        <div
          className={`rounded-xl border p-3 text-[13px] ${
            banner.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          <div className="flex items-center justify-between gap-3">
            <span>{banner.text}</span>
            <button
              className="shrink-0 text-[12px] underline underline-offset-2"
              onClick={() => setBanner(null)}
            >
              dismiss
            </button>
          </div>
        </div>
      )}

      {/* ── Available channels ── */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {/* Google Reviews — REAL connect */}
        <div className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-amber-400 to-red-500 text-[22px] text-white shadow-sm">
            ★
          </div>
          <div className="flex-1">
            <p className="text-[14px] font-semibold text-ink dark:text-fog">Google Reviews</p>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">
              {googleChannels.length > 0
                ? `${googleChannels.length} location${googleChannels.length > 1 ? "s" : ""} connected`
                : "AI replies to your reviews"}
            </p>
          </div>
          <button
            onClick={connectGoogle}
            className="rounded-lg bg-deep-violet px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:opacity-90"
          >
            {googleChannels.length > 0 ? "Add another" : "Connect"}
          </button>
        </div>

        {/* Coming soon */}
        {[
          { name: "Instagram", icon: "📸", color: "from-pink-500 to-purple-500" },
          { name: "Facebook Messenger", icon: "👤", color: "from-blue-500 to-blue-600" },
          { name: "X / Twitter", icon: "🐦", color: "from-sky-400 to-blue-500" },
        ].map((c) => (
          <div
            key={c.name}
            className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 opacity-70 dark:border-fog/[0.06] dark:bg-ink"
          >
            <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${c.color} text-[22px] text-white shadow-sm`}>
              {c.icon}
            </div>
            <div className="flex-1">
              <p className="text-[14px] font-semibold text-ink dark:text-fog">{c.name}</p>
              <p className="text-[12px] text-ink/40 dark:text-fog/40">Auto-reply to DMs</p>
            </div>
            <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[10px] font-semibold text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
              soon
            </span>
          </div>
        ))}
      </div>

      {/* ── Connected Google locations + auto-reply toggle ── */}
      {googleChannels.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Google Business locations</h2>
          {googleChannels.map((c) => {
            const cfg = autoreply[c.id];
            const enabled = cfg?.enabled ?? false;
            return (
              <div
                key={c.id}
                className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink"
              >
                <div className="flex-1">
                  <p className="text-[14px] font-semibold text-ink dark:text-fog">
                    {c.display_name || "Business location"}
                  </p>
                  <p className="text-[12px] text-ink/40 dark:text-fog/40">
                    {enabled ? "AI replies on · 4–5★ auto · 1–3★ need your approval" : "Auto-reply off"}
                  </p>
                </div>
                <button
                  onClick={() => toggleAutoReply(c.id, !enabled)}
                  disabled={busy === c.id}
                  className={`relative h-6 w-11 rounded-full transition ${
                    enabled ? "bg-emerald-500" : "bg-ink/15 dark:bg-fog/15"
                  } ${busy === c.id ? "opacity-50" : ""}`}
                  aria-label={enabled ? "Turn off auto-reply" : "Turn on auto-reply"}
                >
                  <span
                    className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
                      enabled ? "left-[22px]" : "left-0.5"
                    }`}
                  />
                </button>
              </div>
            );
          })}
        </div>
      )}

      {loading && (
        <p className="text-[12px] text-ink/40 dark:text-fog/40">Loading your channels…</p>
      )}
    </div>
  );
}

export default function ChannelsPage() {
  return (
    <Suspense>
      <ConnectHub />
    </Suspense>
  );
}
