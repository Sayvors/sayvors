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
  // "localith" = mirrored from a Localith listing sync (managed on the
  // Localith card); "google" = native Google OAuth. Absent on old backends.
  source?: string | null;
  listing_id?: string | null;
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

/* ── Backend error bodies are JSON {"detail": "..."} — surface the real cause ── */
function errDetail(e: unknown, fallback: string): string {
  const msg = e instanceof Error ? e.message : String(e ?? "");
  try {
    const parsed = JSON.parse(msg) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail.slice(0, 300);
    }
  } catch {
    /* not JSON — use the raw text */
  }
  const t = msg.trim();
  return (t || fallback).slice(0, 300);
}

/* ── AI auto-reply controls: one copy, used by native Google cards AND Localith rows ── */

function AiReplyControls({
  channel,
  cfg,
  busy,
  expanded,
  approvalDraft,
  toneDraft,
  voiceDraft,
  saving,
  onToggle,
  onToggleExpand,
  onApproval,
  onTone,
  onVoice,
  onSave,
}: {
  channel: ApiChannel;
  cfg: AutoReply | null;
  busy: boolean;
  expanded: boolean;
  approvalDraft: "auto" | "approval";
  toneDraft: string;
  voiceDraft: string;
  saving: boolean;
  onToggle: (channelId: string, enable: boolean) => void;
  onToggleExpand: (channelId: string) => void;
  onApproval: (v: "auto" | "approval") => void;
  onTone: (v: string) => void;
  onVoice: (v: string) => void;
  onSave: (channelId: string) => void;
}) {
  const enabled = cfg?.enabled ?? false;
  return (
    <div>
      <div className="flex items-center gap-4">
        <div className="flex-1">
          <p className="text-[12px] text-ink/40 dark:text-fog/40">
            {enabled
              ? cfg?.approval_mode === "approval"
                ? "AI drafts every reply — you approve all"
                : "AI replies on ★4–5 · ★1–3 need your approval"
              : "Auto-reply off"}
          </p>
        </div>
        <button
          onClick={() => onToggleExpand(channel.id)}
          className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-deep-violet transition hover:bg-deep-violet/[0.06]"
        >
          {expanded ? "Close" : "AI settings"}
        </button>
        <button
          onClick={() => onToggle(channel.id, !enabled)}
          disabled={busy}
          className={`relative h-6 w-11 rounded-full transition ${
            enabled ? "bg-emerald-500" : "bg-ink/15 dark:bg-fog/15"
          } ${busy ? "opacity-50" : ""}`}
          aria-label={enabled ? "Turn off auto-reply" : "Turn on auto-reply"}
        >
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
              enabled ? "left-[22px]" : "left-0.5"
            }`}
          />
        </button>
      </div>

      {expanded && (
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
                  onClick={() => onApproval(m.key)}
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
              Response tone
            </p>
            <select
              value={toneDraft}
              onChange={(e) => onTone(e.target.value)}
              aria-label="Response tone"
              className="w-full rounded-lg border border-ink/[0.08] bg-white px-2.5 py-2 text-[12px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              <option value="friendly">Friendly — warm and casual</option>
              <option value="professional">Professional — formal and polished</option>
              <option value="apologetic">Apologetic — extra empathetic</option>
              <option value="playful">Playful — light and fun</option>
              {!["friendly", "professional", "apologetic", "playful"].includes(toneDraft) && (
                <option value={toneDraft}>{toneDraft}</option>
              )}
            </select>
          </div>

          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink/45 dark:text-fog/45">
              Brand voice &amp; house rules
            </p>
            <textarea
              value={voiceDraft}
              onChange={(e) => onVoice(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="e.g. We never promise refunds in replies. Mention our loyalty program to happy customers."
              className="w-full resize-y rounded-lg border border-ink/[0.08] bg-white p-2.5 text-[12px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            />
          </div>

          <button
            onClick={() => onSave(channel.id)}
            disabled={saving}
            className="rounded-lg bg-deep-violet px-3.5 py-2 text-[11px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
          >
            {saving ? (
              <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span>
            ) : "Save AI settings"}
          </button>
        </div>
      )}
    </div>
  );
}

/* ── One connected branch (Localith listing): profile, per-branch sync ── */

function LocalithListingRow({
  listing,
  conn,
  profile,
  busy,
  onEnable,
  onDisable,
  onResync,
  ai,
  approvalDraft,
  toneDraft,
  voiceDraft,
  savingConfig,
  onToggleAi,
  onOpenAi,
  onApprovalAi,
  onToneAi,
  onVoiceAi,
  onSaveAi,
}: {
  listing: { id: string; name: string; address?: string | null };
  conn: LocalithConnection | null;
  profile: LocalithProfile | null;
  busy: boolean;
  onEnable: (listingId: string) => void;
  onDisable: (listingId: string) => void;
  onResync: (listingId: string) => void;
  ai: { channel: ApiChannel; cfg: AutoReply | null; busy: boolean; open: boolean } | null;
  approvalDraft: "auto" | "approval";
  toneDraft: string;
  voiceDraft: string;
  savingConfig: boolean;
  onToggleAi: (channelId: string, enable: boolean) => void;
  onOpenAi: (channelId: string) => void;
  onApprovalAi: (v: "auto" | "approval") => void;
  onToneAi: (v: string) => void;
  onVoiceAi: (v: string) => void;
  onSaveAi: (channelId: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const connected = conn !== null;
  const perf = profile?.metrics?.listings?.[0];
  const rev = profile?.item_metrics?.listings?.[0];
  return (
    <div className={`rounded-xl border p-3 transition ${connected ? "border-emerald-200 bg-emerald-50/60 dark:border-emerald-500/20 dark:bg-emerald-500/[0.06]" : "border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink"}`}>
      <div className="flex items-center gap-2.5">
        <button
          onClick={() => setExpanded((e) => !e)}
          aria-expanded={expanded}
          aria-label={expanded ? "Collapse listing details" : "Expand listing details"}
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ink/40 outline-none transition hover:bg-ink/[0.05] hover:text-ink focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/40 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
        >
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" className={`h-3 w-3 transition-transform ${expanded ? "rotate-180" : ""}`} aria-hidden>
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <span
          aria-hidden
          title={connected ? "Connected" : "Not connected"}
          className={`h-2 w-2 shrink-0 rounded-full ${connected ? "bg-emerald-500" : "bg-ink/20 dark:bg-fog/20"}`}
        />
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 truncate text-[13px] font-semibold text-ink dark:text-fog">
            <span className="truncate">{connected ? conn.listing_name : listing.name}</span>
            {connected ? (
              <>
                {conn.is_verified === true && (
                  <span className="rounded-full bg-emerald-600/15 px-1.5 py-px text-[9px] font-bold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">Verified</span>
                )}
                {typeof conn.total_reviews === "number" && conn.total_reviews > 0 && (
                  <span className="text-[10px] font-medium text-ink/40 dark:text-fog/40">★ {conn.average_rating?.toFixed(1) ?? "–"} · {conn.total_reviews}</span>
                )}
              </>
            ) : (
              <span className="rounded-full bg-ink/[0.05] px-1.5 py-px text-[9px] font-bold uppercase tracking-wide text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">Not connected</span>
            )}
          </p>
          {(listing.address || conn?.address) && (
            <p className="truncate text-[11px] text-ink/45 dark:text-fog/45">
              {listing.address || conn?.address}
            </p>
          )}
        </div>
        {connected && (
          <button
            onClick={() => onResync(listing.id)}
            disabled={busy}
            className="shrink-0 rounded-lg bg-emerald-600 px-2.5 py-1.5 text-[11px] font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
          >
            {busy ? <LogoLoader size={14} /> : "Sync now"}
          </button>
        )}
        <select
          value={connected ? "enabled" : "disabled"}
          disabled={busy}
          onChange={(e) => {
            if (e.target.value === "enabled") onEnable(listing.id);
            else onDisable(listing.id);
          }}
          aria-label={`Enable ${listing.name} in Sayvors`}
          title={connected ? "Disable this listing" : "Enable this listing"}
          className="shrink-0 rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[11px] font-semibold text-ink outline-none transition focus:border-deep-violet/30 disabled:opacity-50 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
        >
          <option value="disabled">Disabled</option>
          <option value="enabled">Enabled</option>
        </select>
      </div>

      {expanded && conn && (
      <>
      {/* Profile snapshot */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-emerald-800/80 dark:text-emerald-200/80">
        {typeof conn.total_reviews === "number" && (
          <span>★ {conn.average_rating?.toFixed(1) ?? "–"} · {conn.total_reviews} review(s)</span>
        )}
        {conn.phone_number && <span>☎ {conn.phone_number}</span>}
        {conn.website_url && (
          <a href={conn.website_url} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2 hover:opacity-80">
            Website
          </a>
        )}
        {conn.maps_url && (
          <a href={conn.maps_url} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2 hover:opacity-80">
            Google Maps
          </a>
        )}
        {conn.last_synced_at && (
          <span className="ml-auto opacity-70">
            Synced {new Date(conn.last_synced_at).toLocaleString()}
          </span>
        )}
      </div>

      {/* Metrics snapshot (trailing window) */}
      {(() => {
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
              Last {conn.metrics_start && conn.metrics_end
                ? `${conn.metrics_start} → ${conn.metrics_end}`
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
      {expanded && ai && (
        <div className="mt-2 border-t border-emerald-200/60 pt-2 dark:border-emerald-500/10">
          <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-emerald-700/60 dark:text-emerald-300/60">
            AI replies
          </p>
          <AiReplyControls
            channel={ai.channel}
            cfg={ai.cfg}
            busy={ai.busy}
            expanded={ai.open}
            approvalDraft={approvalDraft}
            toneDraft={toneDraft}
            voiceDraft={voiceDraft}
            saving={savingConfig}
            onToggle={onToggleAi}
            onToggleExpand={onOpenAi}
            onApproval={onApprovalAi}
            onTone={onToneAi}
            onVoice={onVoiceAi}
            onSave={onSaveAi}
          />
        </div>
      )}
      {conn && (
        <div className="mt-2 flex items-center justify-between gap-2 border-t border-emerald-200/60 pt-2 dark:border-emerald-500/10">
          <span className="text-[11px] text-emerald-700/60 dark:text-emerald-300/60">
            {conn.last_synced_at ? `Synced ${new Date(conn.last_synced_at).toLocaleString()}` : "Not synced yet"}
          </span>
          <button
            onClick={() => onDisable(conn.listing_id)}
            disabled={busy}
            className="rounded-lg px-2 py-1 text-[11px] font-semibold text-emerald-700 transition hover:bg-emerald-100 dark:text-emerald-300 dark:hover:bg-emerald-500/10 disabled:opacity-50"
          >
            Disconnect
          </button>
        </div>
      )}
      </>)}
    </div>
  );
}

function ConnectHub() {
  const params = useSearchParams();
  const [channels, setChannels] = useState<ApiChannel[]>([]);
  const [autoreply, setAutoreply] = useState<Record<string, AutoReply>>({});
  const [expandedConfig, setExpandedConfig] = useState<string | null>(null);
  const [voiceDraft, setVoiceDraft] = useState("");
  const [approvalDraft, setApprovalDraft] = useState<"auto" | "approval">("auto");
  const [toneDraft, setToneDraft] = useState("friendly");
  const [savingConfig, setSavingConfig] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [urlDismissed, setUrlDismissed] = useState(false);

  // Syncs pull reviews + generate AI drafts server-side and can take a
  // while — give them 3 minutes instead of the default 60s timeout.
  const SYNC_TIMEOUT_MS = 180000;

  // ── Localith state: every connected branch is stored, never replaced ──
  const [localithConns, setLocalithConns] = useState<LocalithConnection[]>([]);
  const [localithProfiles, setLocalithProfiles] = useState<Record<string, LocalithProfile>>({});
  const [localithListings, setLocalithListings] = useState<LocalithListing[]>([]);
  const [busyBranch, setBusyBranch] = useState<string | null>(null); // listing_id | "all"

  const connectedCount = params.get("google_connected");
  const googleError = params.get("google_error");
  const metaConnected = params.get("meta_connected");
  const metaError = params.get("meta_error");
  const metaNext = params.get("next");
  const discoveryError = params.get("discovery_error");

  // URL-driven banner derived during render (no effect needed)
  const urlBanner = useMemo(() => {
    if (discoveryError) {
      return {
        kind: "err" as const,
        text: `Connected, but Page/asset discovery failed (Graph ${discoveryError}). Grant the Page in the Meta dialog (pages_show_list) and reconnect.`,
      };
    }
    if (metaConnected !== null) {
      if (metaConnected === "facebook" && metaNext === "instagram_select") {
        return {
          kind: "ok" as const,
          text: "Instagram connected! Open the Instagram card below and click Discover from my Pages.",
        };
      }
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
  }, [connectedCount, googleError, metaConnected, metaError, metaNext, discoveryError]);
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

  // ── Fetch existing Localith connections on mount (all branches) ──
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/integrations/localith/connections");
        if (cancelled) return;
        const conns = (data ?? []) as LocalithConnection[];
        setLocalithConns(conns);
        const profs: Record<string, LocalithProfile> = {};
        await Promise.all(
          conns.map(async (c) => {
            try {
              const prof = await apiFetch(
                `/api/v1/integrations/localith/profile?listing_id=${encodeURIComponent(c.listing_id)}`
              );
              if (prof) profs[c.listing_id] = prof as LocalithProfile;
            } catch {
              /* snapshot missing for this branch — fine */
            }
          })
        );
        if (!cancelled) setLocalithProfiles(profs);
      } catch {
        /* not connected — fine */
      }
      try {
        const data = await apiFetch("/api/v1/integrations/localith/listings");
        if (!cancelled) setLocalithListings(data.listings ?? []);
      } catch {
        /* rows fall back to connected branches only */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const refreshLocalithConns = useCallback(async () => {
    try {
      const data = await apiFetch("/api/v1/integrations/localith/connections");
      const conns = (data ?? []) as LocalithConnection[];
      setLocalithConns(conns);
      return conns;
    } catch {
      return null; // keep stale list
    }
  }, []);

  const refreshLocalithProfile = useCallback(async (listingId: string) => {
    try {
      const prof = await apiFetch(
        `/api/v1/integrations/localith/profile?listing_id=${encodeURIComponent(listingId)}`
      );
      if (prof) setLocalithProfiles((prev) => ({ ...prev, [listingId]: prof as LocalithProfile }));
    } catch {
      /* keep stale snapshot */
    }
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

  const toggleAutoReply = async (channelId: string, enable: boolean) => {
    setBusy(channelId);
    try {
      const cfg = await apiFetch(`/api/v1/channels/${channelId}/autoreply`, {
        method: "PUT",
        body: JSON.stringify({ enabled: enable }),
      });
      setAutoreply((prev) => ({ ...prev, [channelId]: cfg }));
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, "Could not save the auto-reply setting.") });
    } finally {
      setBusy(null);
    }
  };

  const openConfig = (channelId: string) => {
    const cfg = autoreply[channelId];
    setExpandedConfig(expandedConfig === channelId ? null : channelId);
    setVoiceDraft(cfg?.custom_instructions ?? "");
    setApprovalDraft(cfg?.approval_mode === "approval" ? "approval" : "auto");
    setToneDraft(cfg?.tone ?? "friendly");
  };

  const saveConfig = async (channelId: string) => {
    setSavingConfig(true);
    try {
      const cfg = await apiFetch(`/api/v1/channels/${channelId}/autoreply`, {
        method: "PUT",
        body: JSON.stringify({ approval_mode: approvalDraft, custom_instructions: voiceDraft, tone: toneDraft }),
      });
      setAutoreply((prev) => ({ ...prev, [channelId]: cfg }));
      setBanner({ kind: "ok", text: "Response engine settings saved." });
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, "Could not save the response engine settings.") });
    } finally {
      setSavingConfig(false);
    }
  };

  // ── Localith: enable one listing (adds a branch — never replaces) ──
  const enableListing = async (listingId: string) => {
    const keyOf = (l: LocalithListing) => l.id ?? l.googleId ?? l.google_id;
    const chosen = localithListings.find((l) => keyOf(l) === listingId);
    if (!chosen) return;
    setBusyBranch(listingId);
    try {
      await apiFetch("/api/v1/integrations/localith/connection", {
        method: "PUT",
        body: JSON.stringify({
          listing_id: listingId,
          listing_name: chosen.name ?? "Unknown listing",
          listing_google_id: chosen.googleId ?? chosen.google_id ?? null,
        }),
      });
      await refreshLocalithConns();
      try {
        await apiFetch(
          `/api/v1/integrations/localith/sync?listing_id=${encodeURIComponent(listingId)}`,
          { method: "POST" },
          SYNC_TIMEOUT_MS
        );
        await refreshLocalithConns();
        await refreshLocalithProfile(listingId);
        setBanner({ kind: "ok", text: `“${chosen.name ?? listingId}” enabled — synced.` });
      } catch {
        setBanner({ kind: "ok", text: "Listing enabled. Initial sync will retry later." });
      }
    } catch {
      setBanner({ kind: "err", text: "Could not enable listing." });
    } finally {
      setBusyBranch(null);
    }
  };

  // ── Localith: re-sync one branch (or everything when omitted) ──
  const resyncLocalith = async (listingId?: string) => {
    setBusyBranch(listingId ?? "all");
    try {
      const url = listingId
        ? `/api/v1/integrations/localith/sync?listing_id=${encodeURIComponent(listingId)}`
        : "/api/v1/integrations/localith/sync";
      const syncRes = await apiFetch(url, { method: "POST" }, SYNC_TIMEOUT_MS);
      const conns = await refreshLocalithConns();
      if (listingId) {
        await refreshLocalithProfile(listingId);
      } else if (conns) {
        await Promise.all(conns.map((c) => refreshLocalithProfile(c.listing_id)));
      }
      const bits: string[] = [];
      if (typeof syncRes?.fetched === "number") bits.push(`${syncRes.fetched} review(s)`);
      setBanner({ kind: "ok", text: `Localith re-synced: ${bits.join(" · ") || "nothing new"}.` });
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, "Localith sync failed — try again in a minute.") });
    } finally {
      setBusyBranch(null);
    }
  };

  // ── Localith: disconnect one branch (with destructive-data confirmation) ──
  const [confirmDisconnect, setConfirmDisconnect] = useState<string | null>(null);

  const disconnectLocalith = async () => {
    const listingId = confirmDisconnect;
    if (!listingId) return;
    setConfirmDisconnect(null);
    setBusyBranch(listingId);
    try {
      await apiFetch(
        `/api/v1/integrations/localith/connection?listing_id=${encodeURIComponent(listingId)}`,
        { method: "DELETE" }
      );
      setLocalithConns((prev) => prev.filter((c) => c.listing_id !== listingId));
      setLocalithProfiles((prev) => {
        const next = { ...prev };
        delete next[listingId];
        return next;
      });
      setBanner({ kind: "ok", text: "Branch disconnected — its related data was deleted. Other branches untouched." });
    } catch (e) {
      const detail = e instanceof Error ? e.message.slice(0, 200) : "Could not disconnect Localith.";
      setBanner({ kind: "err", text: detail });
    } finally {
      setBusyBranch(null);
    }
  };

  const disconnectTarget = confirmDisconnect
    ? localithConns.find((c) => c.listing_id === confirmDisconnect) ?? null
    : null;

  const googleChannels = channels.filter((c) => c.platform === "google_reviews");

  // Localith-mirrored channels are managed on the Localith card above — the
  // bottom list shows native Google OAuth locations only, so each branch
  // appears exactly once. Falls back to name-matching when the backend
  // predates the `source` field.
  const hasChannelSource = googleChannels.some((c) => c.source != null);
  const localithNameSet = useMemo(
    () => new Set(localithConns.map((c) => c.listing_name.toLowerCase())),
    [localithConns]
  );
  const isLocalithBacked = useCallback(
    (c: ApiChannel) => {
      if (c.source === "localith") return true;
      if (c.source != null) return false;
      if (hasChannelSource) return false;
      return localithNameSet.has((c.display_name || "").toLowerCase());
    },
    [hasChannelSource, localithNameSet]
  );
  const googleChannelsNative = googleChannels.filter((c) => !isLocalithBacked(c));
  const localithChannelByKey = useMemo(() => {
    const m = new Map<string, ApiChannel>();
    for (const c of googleChannels) {
      if (!isLocalithBacked(c)) continue;
      if (c.listing_id) m.set(c.listing_id, c);
      if (c.display_name) m.set(c.display_name.toLowerCase(), c);
    }
    return m;
  }, [googleChannels, isLocalithBacked]);
  const aiForRow = useCallback(
    (conn: LocalithConnection | null) => {
      if (!conn) return null;
      const ch =
        localithChannelByKey.get(conn.listing_id) ??
        localithChannelByKey.get((conn.listing_name || "").toLowerCase()) ??
        null;
      if (!ch) return null;
      return {
        channel: ch,
        cfg: autoreply[ch.id] ?? null,
        busy: busy === ch.id,
        open: expandedConfig === ch.id,
      };
    },
    [localithChannelByKey, autoreply, busy, expandedConfig]
  );

  // Every listing on the Localith account, joined with connection state.
  // Connected branches missing from the API list are appended so nothing vanishes.
  const listingRows = useMemo(() => {
    const keyOf = (l: LocalithListing) => l.id ?? l.googleId ?? l.google_id ?? "";
    const rows = localithListings
      .filter((l) => keyOf(l))
      .map((l) => {
        const id = keyOf(l);
        const conn =
          localithConns.find((c) => c.listing_id === id || c.listing_google_id === id) ?? null;
        return { id, name: l.name ?? id, address: l.address ?? null, conn };
      });
    for (const c of localithConns) {
      if (!rows.some((r) => r.id === c.listing_id)) {
        rows.push({ id: c.listing_id, name: c.listing_name, address: c.address ?? null, conn: c });
      }
    }
    return rows;
  }, [localithListings, localithConns]);

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
        {/* Localith — ONE card: every listing on the account, enabled per row */}
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4 sm:col-span-2 lg:col-span-3 dark:border-fog/[0.06] dark:bg-ink" data-tour="connect-location">
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-400 to-teal-500 text-white shadow-sm">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
              </svg>
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-semibold text-ink dark:text-fog">
                Localith
                {localithConns.length > 0 && (
                  <span className="ml-2 rounded-full bg-emerald-600/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                    {localithConns.length} connected
                  </span>
                )}
              </p>
              <p className="text-[12px] text-ink/40 dark:text-fog/40">Import reviews via middleware — enable each listing below</p>
            </div>
            <button
              onClick={() => void resyncLocalith()}
              disabled={busyBranch !== null || localithConns.length === 0}
              data-tour="sync-now"
              title="Sync every connected branch"
              className="shrink-0 rounded-lg bg-emerald-600 px-3 py-1.5 text-[12px] font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
            >
              {busyBranch === "all" ? <LogoLoader size={14} /> : "Sync all"}
            </button>
          </div>
          <div className="mt-3 space-y-2">
            {listingRows.map((row) => (
              <LocalithListingRow
                key={row.id}
                listing={row}
                conn={row.conn}
                profile={row.conn ? localithProfiles[row.conn.listing_id] ?? null : null}
                busy={busyBranch !== null}
                onEnable={(id) => void enableListing(id)}
                onDisable={(id) => setConfirmDisconnect(id)}
                onResync={(id) => void resyncLocalith(id)}
                ai={aiForRow(row.conn)}
                approvalDraft={approvalDraft}
                toneDraft={toneDraft}
                voiceDraft={voiceDraft}
                savingConfig={savingConfig}
                onToggleAi={(id, enable) => void toggleAutoReply(id, enable)}
                onOpenAi={openConfig}
                onApprovalAi={setApprovalDraft}
                onToneAi={setToneDraft}
                onVoiceAi={setVoiceDraft}
                onSaveAi={(id) => void saveConfig(id)}
              />
            ))}
            {listingRows.length === 0 && (
              <p className="rounded-lg bg-ink/[0.03] px-3 py-2.5 text-[12px] text-ink/45 dark:bg-fog/[0.04] dark:text-fog/45">
                No listings found on the Localith account yet. Add your locations in Localith first, then enable them here.
              </p>
            )}
          </div>
        </div>

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

      {/* ── Native Google OAuth locations only. Localith-mirrored branches
          live on the Localith card above (with their AI controls), so each
          branch appears exactly once. ── */}
      {googleChannelsNative.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Google Business locations</h2>
          {googleChannelsNative.map((c) => (
            <div
              key={c.id}
              className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink"
            >
              <p className="mb-2 text-[14px] font-semibold text-ink dark:text-fog">
                {c.display_name || "Business location"}
              </p>
              <AiReplyControls
                channel={c}
                cfg={autoreply[c.id] ?? null}
                busy={busy === c.id}
                expanded={expandedConfig === c.id}
                approvalDraft={approvalDraft}
                toneDraft={toneDraft}
                voiceDraft={voiceDraft}
                saving={savingConfig}
                onToggle={(id, enable) => void toggleAutoReply(id, enable)}
                onToggleExpand={openConfig}
                onApproval={setApprovalDraft}
                onTone={setToneDraft}
                onVoice={setVoiceDraft}
                onSave={(id) => void saveConfig(id)}
              />
            </div>
          ))}
        </div>
      )}

      {loading && (
        <p className="text-[12px] text-ink/40 dark:text-fog/40">Loading your channels…</p>
      )}

      {/* Disconnect confirmation — destructive, must be explicit, per branch */}
      {confirmDisconnect && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label="Confirm Localith disconnect"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border border-ink/[0.06] bg-white p-5 shadow-2xl dark:border-fog/[0.08] dark:bg-ink">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">
              Disconnect{disconnectTarget ? ` “${disconnectTarget.listing_name}”` : " branch"}?
            </h2>
            <p className="mt-2 text-[13px] leading-relaxed text-ink/60 dark:text-fog/60">
              All data related to this branch will be <strong className="text-red-600">deleted from the database</strong> — location,
              reviews, stats, drafts and settings. Other branches are untouched. This cannot be undone.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setConfirmDisconnect(null)}
                disabled={busyBranch !== null}
                className="rounded-lg px-3.5 py-2 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] dark:text-fog/60 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={disconnectLocalith}
                disabled={busyBranch !== null}
                className="rounded-lg bg-red-600 px-3.5 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:bg-red-700 disabled:opacity-50"
              >
                {busyBranch ? "Deleting…" : "Yes, disconnect & delete data"}
              </button>
            </div>
          </div>
        </div>
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
