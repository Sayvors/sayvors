"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import MetaConnections from "@/components/channels/MetaConnections";
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
  approval_mode?: string;
  custom_instructions?: string | null;
}

interface LocalithListing {
  id: string;
  name?: string;
  google_id?: string;
  googleId?: string;
  source?: string;
  address?: string;
}

interface LocalithConnection {
  id: string;
  listing_id: string;
  listing_name: string;
  listing_google_id: string | null;
  last_synced_at: string | null;
  created_at: string;
  address?: string | null;
  phone_number?: string | null;
  website_url?: string | null;
  maps_url?: string | null;
  store_code?: string | null;
  is_verified?: boolean | null;
  is_disabled?: boolean | null;
  is_suspended?: boolean | null;
  total_reviews?: number;
  average_rating?: number;
  last_review_on?: string | null;
  last_reply_on?: string | null;
  profile_synced_at?: string | null;
  metrics_start?: string | null;
  metrics_end?: string | null;
  metrics_synced_at?: string | null;
}

interface LocalithProfile {
  connection: LocalithConnection;
  listing: Record<string, unknown>;
  metrics: { listings?: Record<string, number | string | null>[] };
  item_metrics: { listings?: Record<string, number | string | null>[] };
}

const GOOGLE_ERRORS: Record<string, string> = {  no_business_account: "No Google Business Profile was found on that Google account.",
  accounts_unavailable: "Google couldn't list your Business Profiles just now (rate limit or permissions). Please try again in a minute.",
  token_exchange_failed: "Google rejected the connection. Please try again.",
  invalid_state: "The connect session expired. Please click Connect again.",
  missing_code: "Google did not return an authorization code. Please try again.",
  access_denied: "You cancelled the Google consent screen.",
};

const META_ERRORS: Record<string, string> = {
  unknown_provider: "Unknown provider.",
  token_exchange_failed: "Meta rejected the connection. Please try again.",
  invalid_state: "The connect session expired. Please click Connect again.",
  missing_code: "Meta did not return an authorization code. Please try again.",
  access_denied: "You cancelled the Meta consent screen.",
};

function num(v: unknown): number {
  const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
  return Number.isFinite(n) ? n : 0;
}

function ConnectHub() {
  const params = useSearchParams();
  const [channels, setChannels] = useState<ApiChannel[]>([]);
  const [autoreply, setAutoreply] = useState<Record<string, AutoReply>>({});
  const [expandedConfig, setExpandedConfig] = useState<string | null>(null);
  const [voiceDraft, setVoiceDraft] = useState("");
  const [approvalDraft, setApprovalDraft] = useState<"auto" | "approval">("auto");
  const [savingConfig, setSavingConfig] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [urlDismissed, setUrlDismissed] = useState(false);

  // ── Localith state ──
  const [localithListing, setLocalithListing] = useState<LocalithConnection | null>(null);
  const [localithListings, setLocalithListings] = useState<LocalithListing[]>([]);
  const [localithOpen, setLocalithOpen] = useState(false);
  const [localithPick, setLocalithPick] = useState<string | null>(null);
  const [localithBusy, setLocalithBusy] = useState(false);
  const [localithProfile, setLocalithProfile] = useState<LocalithProfile | null>(null);

  const connectedCount = params.get("google_connected");
  const googleError = params.get("google_error");
  const metaConnected = params.get("meta_connected");
  const metaError = params.get("meta_error");

  // URL-driven banner derived during render (no effect needed)
  const urlBanner = useMemo(() => {
    if (metaConnected !== null) {
      return {
        kind: "ok" as const,
        text:
          metaConnected === "facebook" || metaConnected === "whatsapp"
            ? `${metaConnected === "facebook" ? "Facebook" : "WhatsApp"} connected! Pick which assets Sayvors should use below.`
            : `Meta connected (${metaConnected})!`,
      };
    }
    if (metaError) {
      return {
        kind: "err" as const,
        text: META_ERRORS[metaError] ?? `Meta connect failed (${metaError}).`,
      };
    }
    if (connectedCount !== null) {
      return {
        kind: "ok" as const,
        text: `Google Reviews connected! ${connectedCount} location(s) added.`,
      };
    }
    if (googleError) {
      return {
        kind: "err" as const,
        text: GOOGLE_ERRORS[googleError] ?? `Google connect failed (${googleError}).`,
      };
    }
    return null;
  }, [connectedCount, googleError, metaConnected, metaError]);
  const activeBanner = banner ?? (urlDismissed ? null : urlBanner);

  const dismissBanner = useCallback(() => {
    setBanner(null);
    setUrlDismissed(true);
    // Strip the OAuth result params so refresh/back never resurrects the banner.
    try {
      window.history.replaceState(null, "", "/dashboard/channels");
    } catch {
      /* history unavailable */
    }
  }, []);

  // ── Fetch existing Localith connection on mount ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const conn = await apiFetch("/api/v1/integrations/localith/connection");
        if (!cancelled) setLocalithListing(conn);
      } catch {
        /* not connected — fine */
      }
      try {
        const prof = await apiFetch("/api/v1/integrations/localith/profile");
        if (!cancelled && prof) {
          setLocalithProfile(prof);
          if (prof.connection) setLocalithListing(prof.connection);
        }
      } catch {
        /* no snapshot yet — fine */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        if (cancelled) return;
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
        if (!cancelled) setAutoreply(configs);
      } catch {
        /* not logged in yet or backend down — cards still render */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

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

  const openConfig = (channelId: string) => {
    const cfg = autoreply[channelId];
    setExpandedConfig(expandedConfig === channelId ? null : channelId);
    setVoiceDraft(cfg?.custom_instructions ?? "");
    setApprovalDraft(cfg?.approval_mode === "approval" ? "approval" : "auto");
  };

  const saveConfig = async (channelId: string) => {
    setSavingConfig(true);
    try {
      const cfg = await apiFetch(`/api/v1/channels/${channelId}/autoreply`, {
        method: "PUT",
        body: JSON.stringify({ approval_mode: approvalDraft, custom_instructions: voiceDraft }),
      });
      setAutoreply((prev) => ({ ...prev, [channelId]: cfg }));
      setBanner({ kind: "ok", text: "Response engine settings saved." });
    } catch {
      setBanner({ kind: "err", text: "Could not save the response engine settings." });
    } finally {
      setSavingConfig(false);
    }
  };

  // ── Localith: fetch available listings ──
  const openLocalithListings = async () => {
    setLocalithOpen(true);
    if (localithListings.length > 0) return;
    try {
      const data = await apiFetch("/api/v1/integrations/localith/listings");
      setLocalithListings(data.listings ?? []);
    } catch {
      setBanner({ kind: "err", text: "Could not fetch Localith listings." });
      setLocalithOpen(false);
    }
  };

  // ── Localith: save chosen listing ──
  const saveLocalith = async () => {
    if (!localithPick) return;
    const keyOf = (l: LocalithListing) => l.id ?? l.googleId ?? l.google_id;
    const chosen = localithListings.find((l) => keyOf(l) === localithPick);
    if (!chosen) return;
    setLocalithBusy(true);
    try {
      const conn = await apiFetch("/api/v1/integrations/localith/connection", {
        method: "PUT",
        body: JSON.stringify({
          listing_id: chosen.id ?? chosen.googleId ?? chosen.google_id,
          listing_name: chosen.name ?? "Unknown listing",
          listing_google_id: chosen.googleId ?? chosen.google_id ?? null,
        }),
      });
      setLocalithListing(conn);
      try {
        const syncRes = await apiFetch("/api/v1/integrations/localith/sync", { method: "POST" });
        const prof = await apiFetch("/api/v1/integrations/localith/profile");
        if (prof) {
          setLocalithProfile(prof);
          if (prof.connection) setLocalithListing(prof.connection);
        }
        const bits: string[] = [];
        if (syncRes?.profile_synced) bits.push("profile");
        if (typeof syncRes?.fetched === "number") bits.push(`${syncRes.fetched} review(s)`);
        if (syncRes?.metrics_synced) bits.push("metrics");
        setBanner({ kind: "ok", text: `Localith connected — synced ${bits.join(" · ") || "nothing yet"}.` });
      } catch {
        setBanner({ kind: "ok", text: "Localith connected. Initial sync will retry later." });
        setLocalithOpen(false);
        return;
      }
      setLocalithOpen(false);
    } catch {
      setBanner({ kind: "err", text: "Could not save Localith connection." });
    } finally {
      setLocalithBusy(false);
    }
  };

  // ── Localith: re-sync everything ──
  const resyncLocalith = async () => {
    setLocalithBusy(true);
    try {
      const syncRes = await apiFetch("/api/v1/integrations/localith/sync", { method: "POST" });
      const prof = await apiFetch("/api/v1/integrations/localith/profile");
      if (prof) {
        setLocalithProfile(prof);
        if (prof.connection) setLocalithListing(prof.connection);
      }
      const bits: string[] = [];
      if (syncRes?.profile_synced) bits.push("profile");
      if (typeof syncRes?.fetched === "number") bits.push(`${syncRes.fetched} review(s)`);
      if (syncRes?.metrics_synced) bits.push("metrics");
      setBanner({ kind: "ok", text: `Localith re-synced: ${bits.join(" · ") || "nothing new"}.` });
    } catch {
      setBanner({ kind: "err", text: "Localith sync failed — try again in a minute." });
    } finally {
      setLocalithBusy(false);
    }
  };

  // ── Localith: disconnect ──
  const disconnectLocalith = async () => {
    setLocalithBusy(true);
    try {
      await apiFetch("/api/v1/integrations/localith/connection", { method: "DELETE" });
      setLocalithListing(null);
      setLocalithProfile(null);
      setBanner({ kind: "ok", text: "Localith disconnected." });
    } catch {
      setBanner({ kind: "err", text: "Could not disconnect Localith." });
    } finally {
      setLocalithBusy(false);
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

      {activeBanner && (
        <div
          className={`rounded-xl border p-3 text-[13px] ${
            activeBanner.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-700"
          }`}
        >
          <div className="flex items-center justify-between gap-3">
            <span>{activeBanner.text}</span>
            <button
              className="shrink-0 text-[12px] underline underline-offset-2"
              onClick={dismissBanner}
            >
              dismiss
            </button>
          </div>
        </div>
      )}

      {/* ── Available channels ── */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {/* Google Reviews — REAL connect */}
        <div className="animate-google-glow rounded-xl p-[2px] shadow-[0_0_28px_-8px_rgba(66,133,244,0.55)]">
        <div className="relative flex items-center gap-4 rounded-[10px] bg-white p-4 dark:bg-ink">
          <span className="absolute -top-2.5 left-4 rounded-full bg-gradient-to-r from-[#4285F4] to-[#34A853] px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white shadow-sm">
            Recommended
          </span>
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-white shadow-sm ring-1 ring-ink/[0.08] dark:ring-fog/10">
            <Image src="/google.svg" alt="Google" width={28} height={28} className="h-7 w-7" />
          </div>
          <div className="flex-1">
            <p className="text-[14px] font-semibold">
              <span aria-hidden>
                <span className="text-[#4285F4]">G</span>
                <span className="text-[#EA4335]">o</span>
                <span className="text-[#FBBC05]">o</span>
                <span className="text-[#4285F4]">g</span>
                <span className="text-[#34A853]">l</span>
                <span className="text-[#EA4335]">e</span>
              </span>
              <span className="sr-only">Google</span>
              <span className="text-ink dark:text-fog"> Reviews</span>
            </p>
            <p className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5 shrink-0" aria-hidden>
                <path d="M3 9l1.5-5h15L21 9" />
                <path d="M3 9h18v2a2.5 2.5 0 01-5 0 2.5 2.5 0 01-5 0 2.5 2.5 0 01-5 0V9z" />
                <path d="M5 12.5V20h14v-7.5" />
                <path d="M9 20v-5h6v5" />
              </svg>
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
        </div>

        {/* Localith — review middleware (no Google approval needed) */}
        {localithListing ? (
          <div className="space-y-3 rounded-xl border border-emerald-200 bg-emerald-50/60 p-4 dark:border-emerald-500/20 dark:bg-emerald-500/[0.06]">
            <div className="flex items-center gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-white shadow-sm ring-1 ring-emerald-200/60 dark:ring-emerald-500/20">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 text-emerald-600">
                  <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
                </svg>
              </div>
              <div className="flex-1 min-w-0">
                <p className="flex items-center gap-1.5 text-[14px] font-semibold text-emerald-800 dark:text-emerald-300">
                  Localith
                  {localithListing.is_verified === true && (
                    <span className="rounded-full bg-emerald-600/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">Verified</span>
                  )}
                  {localithListing.is_suspended === true && (
                    <span className="rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-red-600">Suspended</span>
                  )}
                </p>
                <p className="truncate text-[12px] font-medium text-emerald-700/80 dark:text-emerald-300/80">
                  {localithListing.listing_name}
                </p>
                {localithListing.address && (
                  <p className="truncate text-[11px] text-emerald-700/60 dark:text-emerald-300/60">
                    {localithListing.address}
                  </p>
                )}
              </div>
              <button
                onClick={resyncLocalith}
                disabled={localithBusy}
                className="rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[11px] font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
              >
                {localithBusy ? <LogoLoader size={14} /> : "Sync now"}
              </button>
              <button
                onClick={disconnectLocalith}
                disabled={localithBusy}
                className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-emerald-700 transition hover:bg-emerald-100 dark:text-emerald-300 dark:hover:bg-emerald-500/10 disabled:opacity-50"
              >
                Disconnect
              </button>
            </div>

            {/* Profile snapshot */}
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-emerald-800/80 dark:text-emerald-200/80">
              {typeof localithListing.total_reviews === "number" && (
                <span>★ {localithListing.average_rating?.toFixed(1) ?? "–"} · {localithListing.total_reviews} review(s)</span>
              )}
              {localithListing.phone_number && <span>☎ {localithListing.phone_number}</span>}
              {localithListing.website_url && (
                <a href={localithListing.website_url} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2 hover:opacity-80">
                  Website
                </a>
              )}
              {localithListing.maps_url && (
                <a href={localithListing.maps_url} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2 hover:opacity-80">
                  Google Maps
                </a>
              )}
              {localithListing.last_synced_at && (
                <span className="ml-auto opacity-70">
                  Synced {new Date(localithListing.last_synced_at).toLocaleString()}
                </span>
              )}
            </div>

            {/* Metrics snapshot (trailing window) */}
            {(() => {
              const perf = localithProfile?.metrics?.listings?.[0];
              const rev = localithProfile?.item_metrics?.listings?.[0];
              if (!perf && !rev) return null;
              const impressions = perf
                ? num(perf.googleMapsDesktop) + num(perf.googleMapsMobile) + num(perf.googleSearchDesktop) + num(perf.googleSearchMobile)
                : 0;
              const cells: [string, string][] = [];
              if (perf) {
                cells.push(["Impressions", String(impressions)]);
                cells.push(["Website clicks", String(num(perf.websiteClicks))]);
                cells.push(["Calls", String(num(perf.callClicks))]);
                cells.push(["Directions", String(num(perf.directions))]);
              }
              if (rev) {
                cells.push(["Replies", String(num(rev.numberReplies))]);
                cells.push(["👍/😐/👎", `${num(rev.positiveReviews)}/${num(rev.neutralReviews)}/${num(rev.negativeReviews)}`]);
              }
              return (
                <div>
                  <p className="mb-1.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700/60 dark:text-emerald-300/60">
                    Last {localithListing.metrics_start && localithListing.metrics_end
                      ? `${localithListing.metrics_start} → ${localithListing.metrics_end}`
                      : "30 days"}
                  </p>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                    {cells.map(([label, value]) => (
                      <div key={label} className="rounded-lg bg-white/70 px-2 py-1.5 text-center ring-1 ring-emerald-200/50 dark:bg-emerald-500/[0.08]">
                        <p className="text-[14px] font-bold text-emerald-900 dark:text-emerald-100">{value}</p>
                        <p className="text-[9px] font-medium uppercase tracking-wide text-emerald-700/60 dark:text-emerald-300/60">{label}</p>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })()}
          </div>
        ) : (
          <div className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-500 text-[20px] text-white shadow-sm">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
              </svg>
            </div>
            <div className="flex-1">
              <p className="text-[14px] font-semibold text-ink dark:text-fog">Localith</p>
              <p className="text-[12px] text-ink/40 dark:text-fog/40">Import reviews via middleware</p>
            </div>
            {localithOpen ? (
              <div className="flex items-center gap-2">
                <select
                  value={localithPick ?? ""}
                  onChange={(e) => setLocalithPick(e.target.value || null)}
                  className="w-48 rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[12px] text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
                >
                  <option value="">Select listing...</option>
                  {localithListings.map((l) => (
                    <option key={l.id ?? l.googleId ?? l.google_id} value={l.id ?? l.googleId ?? l.google_id}>
                      {l.name ?? l.id}
                    </option>
                  ))}
                </select>
                <button
                  onClick={saveLocalith}
                  disabled={!localithPick || localithBusy}
                  className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50"
                >
                  {localithBusy ? <span className="inline-flex items-center gap-1"><LogoLoader size={12} /> </span> : "Save"}
                </button>
                <button
                  onClick={() => setLocalithOpen(false)}
                  className="rounded-lg px-2 py-1.5 text-[11px] font-semibold text-ink/40 transition hover:bg-ink/[0.04] dark:text-fog/40"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={openLocalithListings}
                className="rounded-lg bg-deep-violet px-3.5 py-1.5 text-[12px] font-semibold text-white transition hover:opacity-90"
              >
                Connect
              </button>
            )}
          </div>
        )}

        {/* Meta connections — tenant-owned WhatsApp / Facebook / Instagram */}
        <MetaConnections
          onNotice={(kind, text) => setBanner({ kind, text })}
        />

        {/* Coming soon */}
        {[
          { name: "X / Twitter", icon: "\u{1F426}", color: "from-sky-400 to-blue-500" },
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
                className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink"
              >
                <div className="flex items-center gap-4">
                  <div className="flex-1">
                    <p className="text-[14px] font-semibold text-ink dark:text-fog">
                      {c.display_name || "Business location"}
                    </p>
                    <p className="text-[12px] text-ink/40 dark:text-fog/40">
                      {enabled
                        ? cfg?.approval_mode === "approval"
                          ? "AI drafts every reply — you approve all"
                          : "AI replies on ★4–5 · ★1–3 need your approval"
                        : "Auto-reply off"}
                    </p>
                  </div>
                  <button
                    onClick={() => openConfig(c.id)}
                    className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-deep-violet transition hover:bg-deep-violet/[0.06]"
                  >
                    {expandedConfig === c.id ? "Close" : "AI settings"}
                  </button>
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

                {expandedConfig === c.id && (
                  <div className="mt-4 space-y-4 border-t border-ink/[0.05] pt-4">
                    <div>
                      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink/45 dark:text-fog/45">
                        Approval mode
                      </p>
                      <div className="flex rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.06]">
                        {([
                          { key: "auto", label: "Fully automatic" },
                          { key: "approval", label: "I approve everything" },
                        ] as const).map((m) => (
                          <button
                            key={m.key}
                            onClick={() => setApprovalDraft(m.key)}
                            aria-pressed={approvalDraft === m.key}
                            className={`flex-1 rounded-md px-2 py-1.5 text-[11px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                              approvalDraft === m.key
                                ? "bg-white text-deep-violet shadow-sm dark:bg-ink"
                                : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
                            }`}
                          >
                            {m.label}
                          </button>
                        ))}
                      </div>
                      <p className="mt-1 text-[10px] text-ink/35 dark:text-fog/35">
                        Automatic: replies post instantly above your rating threshold. Approval: every draft waits for you.
                      </p>
                    </div>

                    <div>
                      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink/45 dark:text-fog/45">
                        Brand voice &amp; house rules
                      </p>
                      <textarea
                        value={voiceDraft}
                        onChange={(e) => setVoiceDraft(e.target.value)}
                        rows={3}
                        maxLength={2000}
                        placeholder="e.g. We never promise refunds in replies. Mention our loyalty program to happy customers."
                        className="w-full resize-y rounded-lg border border-ink/[0.08] bg-white p-2.5 text-[12px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
                      />
                    </div>

                    <button
                      onClick={() => saveConfig(c.id)}
                      disabled={savingConfig}
                      className="rounded-lg bg-deep-violet px-3.5 py-2 text-[11px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
                    >
                      {savingConfig ? (
                        <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span>
                      ) : "Save AI settings"}
                    </button>
                  </div>
                )}
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
