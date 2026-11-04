"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { useUpdateChannelConfig } from "@/lib/mutation-hooks";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import MetaConnections from "@/components/channels/MetaConnections";
import PlatformMark from "@/components/channels/PlatformMark";
import { setActiveConnectImport } from "@/lib/connect-import";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ApiChannel {
  id: string;
  platform: string;
  display_name: string | null;
  status: string;
  created_at: string;
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

const GOOGLE_ERRORS: Record<string, string> = {
  no_business_account: "No Google Business Profile was found on that Google account.",
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
  pendingCount,
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
  pendingCount: number;
}) {
  const enabled = cfg?.enabled ?? false;
  return (
    <div>
      <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-[12px] text-ink/40 dark:text-fog/40">
            {enabled
              ? cfg?.approval_mode === "approval"
                ? "AI drafts every reply — you approve all"
                : "AI replies on ★4–5 · ★1–3 need your approval"
              : "Auto-reply off"}
          </p>
          {pendingCount > 0 && (
            <Link
              href="/dashboard/outbox"
              className="mt-1 inline-block rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600 outline-none transition hover:bg-amber-500/20 focus-visible:ring-2 focus-visible:ring-deep-violet/40"
            >
              {pendingCount} awaiting approval →
            </Link>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={() => onToggleExpand(channel.id)}
            className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-deep-violet transition hover:bg-deep-violet/[0.06]"
          >
            {expanded ? "Close" : "AI settings"}
          </button>
          <button
            onClick={() => onToggle(channel.id, !enabled)}
            disabled={busy}
            className={`relative h-6 w-11 shrink-0 rounded-full transition ${
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
            className="min-h-8 rounded-lg bg-deep-violet px-3.5 py-2 text-[11px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
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

function ConnectHub() {
  const params = useSearchParams();
  const queryClient = useQueryClient();
  const updateConfig = useUpdateChannelConfig();
  const [channels, setChannels] = useState<ApiChannel[]>([]);
  const [autoreply, setAutoreply] = useState<Record<string, AutoReply>>({});
  const [pending, setPending] = useState<Record<string, number>>({});
  const [expandedConfig, setExpandedConfig] = useState<string | null>(null);
  const [voiceDraft, setVoiceDraft] = useState("");
  const [approvalDraft, setApprovalDraft] = useState<"auto" | "approval">("auto");
  const [toneDraft, setToneDraft] = useState("friendly");
  const [savingConfig, setSavingConfig] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [urlDismissed, setUrlDismissed] = useState(false);
  const [confirmGoogleDisconnect, setConfirmGoogleDisconnect] = useState(false);

  const connectedCount = params.get("google_connected");
  const googleError = params.get("google_error");
  const metaConnected = params.get("meta_connected");
  const metaError = params.get("meta_error");
  const metaNext = params.get("next");
  const discoveryError = params.get("discovery_error");
  const importSession = params.get("import_session");

  useEffect(() => {
    if (importSession) setActiveConnectImport(importSession);
  }, [importSession]);

  const urlBanner = useMemo(() => {
    if (discoveryError) {
      return {
        kind: "err" as const,
        text: `Connected, but Page/asset discovery failed (Graph ${discoveryError}). Grant the Page in the Meta dialog (pages_show_list) and reconnect.`,
      };
    }
    if (metaConnected !== null) {
      if (metaConnected === "facebook" && metaNext === "instagram_select") {
        return { kind: "ok" as const, text: "Instagram connected — looking for accounts linked to your Pages…" };
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
      return { kind: "err" as const, text: META_ERRORS[metaError] ?? `Meta connect failed (${metaError}).` };
    }
    if (connectedCount !== null) {
      return { kind: "ok" as const, text: `Google Business Profile connected! ${connectedCount} location(s) added.` };
    }
    if (googleError) {
      return { kind: "err" as const, text: GOOGLE_ERRORS[googleError] ?? `Google connect failed (${googleError}).` };
    }
    return null;
  }, [connectedCount, googleError, metaConnected, metaError, metaNext, discoveryError]);
  const activeBanner = banner ?? (urlDismissed ? null : urlBanner);

  const dismissBanner = useCallback(() => {
    setBanner(null);
    setUrlDismissed(true);
    try {
      window.history.replaceState(null, "", "/dashboard/channels");
    } catch {
      /* history unavailable */
    }
  }, []);

  const connectGoogle = useCallback(async () => {
    setGoogleBusy(true);
    setBanner(null);
    try {
      const data = await apiFetch("/api/v1/channels/google/connect-ticket", { method: "POST" });
      const ticket = typeof data?.ticket === "string" ? data.ticket : "";
      if (!ticket) throw new Error("Google connect is not configured yet.");
      window.location.href = `${API}/api/v1/channels/google/connect?ticket=${encodeURIComponent(ticket)}&next=/dashboard/channels`;
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, "Could not start Google connect. Please try again.") });
      setGoogleBusy(false);
    }
  }, []);

  const disconnectGoogle = useCallback(async () => {
    setGoogleBusy(true);
    try {
      const res = await apiFetch("/api/v1/channels/google/disconnect", { method: "POST" });
      const count = typeof res?.disconnected === "number" ? res.disconnected : 0;
      setBanner({
        kind: "ok",
        text: `Google disconnected (${count} location${count === 1 ? "" : "s"}). Your data is kept and will return when you reconnect.`,
      });
      setConfirmGoogleDisconnect(false);
      await queryClient.invalidateQueries();
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, "Could not disconnect Google. Please try again.") });
    } finally {
      setGoogleBusy(false);
    }
  }, [queryClient]);

  const channelsQuery = useQuery({
    queryKey: queryKeys.channels.list(100),
    queryFn: async () => {
      const data = await apiFetch("/api/v1/channels?limit=100&include_disconnected=true");
      const chs = (data.channels ?? []) as ApiChannel[];
      const configs: Record<string, AutoReply> = {};
      const pend: Record<string, number> = {};
      await Promise.all(
        chs
          .filter((c: ApiChannel) => c.platform === "google_reviews" && c.status === "active")
          .map(async (c: ApiChannel) => {
            try {
              const cfg = await apiFetch(`/api/v1/channels/${c.id}/autoreply`);
              configs[c.id] = cfg;
            } catch {
              /* config endpoint creates default on first GET; ignore errors */
            }
            try {
              const r = await apiFetch(`/api/v1/channels/${c.id}/reviews?status=pending_approval&limit=1`);
              pend[c.id] = r.pending ?? 0;
            } catch {
              pend[c.id] = 0;
            }
          })
      );
      return { channels: chs, configs, pend };
    },
    staleTime: 30 * 1000,
  });
  useEffect(() => {
    const d = channelsQuery.data;
    if (!d) return;
    setChannels(d.channels);
    setAutoreply(d.configs);
    setPending(d.pend);
    setLoading(false);
  }, [channelsQuery.data]);

  const toggleAutoReply = async (channelId: string, enable: boolean) => {
    setBusy(channelId);
    try {
      const cfg = await updateConfig.mutateAsync({ channelId, body: { enabled: enable } });
      setAutoreply((prev) => ({ ...prev, [channelId]: cfg as AutoReply }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.channels.list(100) });
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
      const cfg = await updateConfig.mutateAsync({
        channelId,
        body: { approval_mode: approvalDraft, custom_instructions: voiceDraft, tone: toneDraft },
      });
      setAutoreply((prev) => ({ ...prev, [channelId]: cfg as AutoReply }));
      void queryClient.invalidateQueries({ queryKey: queryKeys.channels.list(100) });
      setBanner({ kind: "ok", text: "Response engine settings saved." });
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, "Could not save the response engine settings.") });
    } finally {
      setSavingConfig(false);
    }
  };

  const googleChannels = channels.filter((c) => c.platform === "google_reviews");
  const googleActive = googleChannels.filter((c) => c.status === "active");
  const googleExpired = googleChannels.filter((c) => c.status === "expired");
  const googleDisconnected = googleChannels.filter((c) => c.status === "disconnected");
  const hasGoogle = googleChannels.length > 0;
  const needsReconnect = googleExpired.length > 0 || (googleActive.length === 0 && googleDisconnected.length > 0);

  return (
    <div className="h-full overflow-y-auto p-4 pb-24 space-y-5 sm:p-6">
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
            <button className="shrink-0 text-[12px] underline underline-offset-2" onClick={dismissBanner}>
              dismiss
            </button>
          </div>
        </div>
      )}

      <section className="space-y-2">
        <h2 className="text-[11px] font-bold uppercase tracking-wide text-ink/40 dark:text-fog/40">
          Google reviews &amp; locations
        </h2>
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border border-ink/[0.06] bg-white dark:border-fog/[0.08] dark:bg-ink">
              <PlatformMark platform="google_reviews" size={24} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[14px] font-semibold text-ink dark:text-fog">Google Business Profile</p>
                <span className="rounded-full bg-[#1a73e8]/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#1a73e8] dark:bg-[#8ab4f8]/15 dark:text-[#8ab4f8]">
                  Official API
                </span>
                {googleActive.length > 0 && (
                  <span className="rounded-full bg-emerald-600/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                    {googleActive.length} connected
                  </span>
                )}
                {googleExpired.length > 0 && (
                  <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-700 dark:text-amber-300">
                    reconnection needed
                  </span>
                )}
                {googleActive.length === 0 && googleDisconnected.length > 0 && (
                  <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50">
                    disconnected
                  </span>
                )}
              </div>
              <p className="text-[12px] text-ink/40 dark:text-fog/40">
                Connect your Business Profile directly — reviews, replies, locations and performance sync from Google.
              </p>
              {needsReconnect && (
                <p className="mt-1 text-[11px] leading-snug text-amber-700 dark:text-amber-300">
                  {googleDisconnected.length > 0 && googleActive.length === 0
                    ? "Google is disconnected. Your locations, reviews and analytics are hidden — nothing was deleted. Reconnect to restore the same data."
                    : "Your Google connection expired. Reconnect to keep syncing reviews and performance."}
                </p>
              )}
            </div>
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {googleActive.length > 0 && (
                <button
                  onClick={() => setConfirmGoogleDisconnect(true)}
                  disabled={googleBusy}
                  className="min-h-8 rounded-lg border border-red-200 px-3 py-1.5 text-[12px] font-semibold text-red-600 transition hover:bg-red-50 disabled:opacity-50 dark:border-red-500/30 dark:text-red-400 dark:hover:bg-red-500/10"
                >
                  Disconnect Google
                </button>
              )}
              <button
                onClick={() => void connectGoogle()}
                disabled={googleBusy}
                className="min-h-8 rounded-lg bg-[#1a73e8] px-3 py-1.5 text-[12px] font-semibold text-white transition hover:bg-[#1765cc] disabled:opacity-50"
              >
                {googleBusy ? (
                  <LogoLoader size={14} />
                ) : hasGoogle ? (
                  "Reconnect / add locations"
                ) : (
                  "Connect Google Business"
                )}
              </button>
            </div>
          </div>
        </div>

        {googleActive.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-[13px] font-semibold text-ink dark:text-fog">Google Business locations</h3>
            {googleActive.map((c) => (
              <div key={c.id} className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
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
                  pendingCount={pending[c.id] ?? 0}
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
      </section>

      <section className="space-y-3">
        <div>
          <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Messaging &amp; social</h2>
          <p className="text-[11px] text-ink/35 dark:text-fog/35">Meta — your own business accounts</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <MetaConnections onNotice={(kind, text) => setBanner({ kind, text })} />
          <article className="flex flex-col rounded-xl border border-ink/[0.06] bg-white p-4 opacity-70 dark:border-fog/[0.06] dark:bg-ink">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-ink/[0.04] dark:bg-fog/[0.06]">
                <PlatformMark platform="x" size={20} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <p className="text-[13.5px] font-semibold text-ink dark:text-fog">X / Twitter</p>
                  <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:bg-fog/[0.07] dark:text-fog/45">
                    Soon
                  </span>
                </div>
                <p className="mt-0.5 truncate text-[11.5px] text-ink/45 dark:text-fog/45">Auto-reply to DMs</p>
              </div>
            </div>
          </article>
        </div>
      </section>

      {loading && <p className="text-[12px] text-ink/40 dark:text-fog/40">Loading your channels…</p>}

      {confirmGoogleDisconnect && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label="Confirm Google disconnect"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
        >
          <div className="w-full max-w-md rounded-2xl border border-ink/[0.06] bg-white p-4 shadow-2xl dark:border-fog/[0.08] dark:bg-ink sm:p-5">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">Disconnect Google Business Profile?</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-ink/60 dark:text-fog/60">
              Your Google locations, reviews, analytics and posts will be <strong>hidden from Sayvors</strong>.
              Nothing is deleted — the data stays in Sayvors and on Google. Reconnecting restores the same
              locations, reviews and history.
            </p>
            <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                onClick={() => setConfirmGoogleDisconnect(false)}
                disabled={googleBusy}
                className="rounded-lg border border-ink/10 px-3.5 py-2 text-[12px] font-semibold text-ink/70 dark:border-fog/10 dark:text-fog/70"
              >
                Cancel
              </button>
              <button
                onClick={() => void disconnectGoogle()}
                disabled={googleBusy}
                className="rounded-lg bg-red-600 px-3.5 py-2 text-[12px] font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {googleBusy ? <LogoLoader size={14} /> : "Disconnect Google"}
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
