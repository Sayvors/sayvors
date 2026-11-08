"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import { useUpdateChannelConfig } from "@/lib/mutation-hooks";
import { useI18n } from "@/lib/i18n/I18nProvider";
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

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
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
  const { t } = useI18n();
  const a = t.dashboard.channels.ai;
  const enabled = cfg?.enabled ?? false;
  return (
    <div>
      <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-[12px] text-ink/40 dark:text-fog/40">
            {enabled
              ? cfg?.approval_mode === "approval"
                ? a.draftApproval
                : a.autoRule
              : a.autoOff}
          </p>
          {pendingCount > 0 && (
            <Link
              href="/dashboard/outbox"
              className="mt-1 inline-block rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-amber-600 outline-none transition hover:bg-amber-500/20 focus-visible:ring-2 focus-visible:ring-deep-violet/40"
            >
              {fill(a.awaiting, { count: pendingCount })}
            </Link>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            onClick={() => onToggleExpand(channel.id)}
            className="rounded-lg px-2.5 py-1.5 text-[11px] font-semibold text-deep-violet transition hover:bg-deep-violet/[0.06]"
          >
            {expanded ? a.close : a.settings}
          </button>
          <button
            onClick={() => onToggle(channel.id, !enabled)}
            disabled={busy}
            className={`relative h-6 w-11 shrink-0 rounded-full transition ${
              enabled ? "bg-emerald-500" : "bg-ink/15 dark:bg-fog/15"
            } ${busy ? "opacity-50" : ""}`}
            aria-label={enabled ? a.toggleOff : a.toggleOn}
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
              {a.approvalTitle}
            </p>
            <div className="flex rounded-lg bg-ink/[0.03] p-0.5 dark:bg-fog/[0.06]">
              {([
                { key: "auto", label: a.autoLabel, aria: "auto" },
                { key: "approval", label: a.approvalLabel, aria: "approval" },
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
              {a.approvalDesc}
            </p>
          </div>

          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink/45 dark:text-fog/45">
              {a.toneTitle}
            </p>
            <select
              value={toneDraft}
              onChange={(e) => onTone(e.target.value)}
              aria-label={a.toneTitle}
              className="w-full rounded-lg border border-ink/[0.08] bg-white px-2.5 py-2 text-[12px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              <option value="friendly">{a.friendly}</option>
              <option value="professional">{a.professional}</option>
              <option value="apologetic">{a.apologetic}</option>
              <option value="playful">{a.playful}</option>
              {!["friendly", "professional", "apologetic", "playful"].includes(toneDraft) && (
                <option value={toneDraft}>{toneDraft}</option>
              )}
            </select>
          </div>

          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink/45 dark:text-fog/45">
              {a.voiceTitle}
            </p>
            <textarea
              value={voiceDraft}
              onChange={(e) => onVoice(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder={a.voicePh}
              className="w-full resize-y rounded-lg border border-ink/[0.08] bg-white p-2.5 text-[12px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            />
          </div>

          <button
            onClick={() => onSave(channel.id)}
            disabled={saving}
            className="min-h-8 rounded-lg bg-deep-violet px-3.5 py-2 text-[11px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
          >
            {saving ? (
              <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> {a.saving}</span>
            ) : a.save}
          </button>
        </div>
      )}
    </div>
  );
}

function ConnectHub() {
  const params = useSearchParams();
  const { t } = useI18n();
  const ch = t.dashboard.channels;
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

  const googleErrorText = googleError
    ? {
        no_business_account: ch.googleErrors.noBusiness,
        accounts_unavailable: ch.googleErrors.noAccounts,
        token_exchange_failed: ch.googleErrors.tokenFailed,
        invalid_state: ch.googleErrors.badState,
        missing_code: ch.googleErrors.noCode,
        access_denied: ch.googleErrors.denied,
      }[googleError] ?? fill(ch.banners.googleFailed, { code: googleError })
    : null;
  const metaErrorText = metaError
    ? {
        unknown_provider: ch.metaErrors.unknownProvider,
        provider_disabled: ch.metaErrors.providerPaused,
        token_exchange_failed: ch.metaErrors.tokenFailed,
        invalid_state: ch.metaErrors.badState,
        missing_code: ch.metaErrors.noCode,
        access_denied: ch.metaErrors.denied,
      }[metaError] ?? fill(ch.banners.metaFailed, { code: metaError })
    : null;

  const urlBanner = useMemo(() => {
    if (discoveryError) {
      return {
        kind: "err" as const,
        text: fill(ch.banners.discovery, { code: discoveryError }),
      };
    }
    if (metaConnected !== null) {
      if (metaConnected === "facebook" && metaNext === "instagram_select") {
        return { kind: "ok" as const, text: ch.banners.igConnected };
      }
      return {
        kind: "ok" as const,
        text:
          metaConnected === "facebook"
            ? ch.banners.fbConnected
            : metaConnected === "whatsapp"
              ? ch.banners.waConnected
              : fill(ch.banners.metaConnected, { provider: metaConnected }),
      };
    }
    if (metaErrorText) {
      return { kind: "err" as const, text: metaErrorText };
    }
    if (connectedCount !== null) {
      return { kind: "ok" as const, text: fill(ch.banners.googleConnected, { count: connectedCount }) };
    }
    if (googleErrorText) {
      return { kind: "err" as const, text: googleErrorText };
    }
    return null;
  }, [connectedCount, googleError, googleErrorText, metaConnected, metaError, metaErrorText, metaNext, discoveryError, ch]);
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
      if (!ticket) throw new Error(ch.actions.googleNotConfigured);
      window.location.href = `${API}/api/v1/channels/google/connect?ticket=${encodeURIComponent(ticket)}&next=/dashboard/channels`;
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, ch.actions.googleStartFailed) });
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
        text: fill(ch.actions.googleDisconnected, { count }),
      });
      setConfirmGoogleDisconnect(false);
      await queryClient.invalidateQueries();
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, ch.actions.googleDisconnectFailed) });
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
      setBanner({ kind: "err", text: errDetail(e, ch.actions.autoSaveFailed) });
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
      setBanner({ kind: "ok", text: ch.actions.aiSaved });
    } catch (e) {
      setBanner({ kind: "err", text: errDetail(e, ch.actions.aiSaveFailed) });
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
        <h1 className="text-[20px] font-bold text-ink dark:text-fog">{ch.hub.title}</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
          {ch.hub.subtitle}
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
              {t.common.dismiss}
            </button>
          </div>
        </div>
      )}

      <section className="space-y-2">
        <h2 className="text-[11px] font-bold uppercase tracking-wide text-ink/40 dark:text-fog/40">
          {ch.hub.googleSection}
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
                  {ch.hub.official}
                </span>
                {googleActive.length > 0 && (
                  <span className="rounded-full bg-emerald-600/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
                    {fill(ch.hub.connectedN, { count: googleActive.length })}
                  </span>
                )}
                {googleExpired.length > 0 && (
                  <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-amber-700 dark:text-amber-300">
                    {ch.hub.reconnect}
                  </span>
                )}
                {googleActive.length === 0 && googleDisconnected.length > 0 && (
                  <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50">
                    {ch.hub.disconnected}
                  </span>
                )}
              </div>
              <p className="text-[12px] text-ink/40 dark:text-fog/40">
                {ch.hub.googleDesc}
              </p>
              {needsReconnect && (
                <p className="mt-1 text-[11px] leading-snug text-amber-700 dark:text-amber-300">
                  {googleDisconnected.length > 0 && googleActive.length === 0
                    ? ch.hub.disconnectedMsg
                    : ch.hub.expiredMsg}
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
                  {ch.hub.disconnectGoogle}
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
                  ch.hub.reconnectGoogle
                ) : (
                  ch.hub.connectGoogle
                )}
              </button>
            </div>
          </div>
        </div>

        {googleActive.length > 0 && (
          <div className="space-y-3">
            <h3 className="text-[13px] font-semibold text-ink dark:text-fog">{ch.hub.locationsTitle}</h3>
            {googleActive.map((c) => (
              <div key={c.id} className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                <p className="mb-2 text-[14px] font-semibold text-ink dark:text-fog">
                  {c.display_name || ch.hub.businessLocation}
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
          <h2 className="text-[15px] font-semibold text-ink dark:text-fog">{ch.hub.messagingTitle}</h2>
          <p className="text-[11px] text-ink/35 dark:text-fog/35">{ch.hub.messagingSub}</p>
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
                    {ch.hub.soon}
                  </span>
                </div>
                <p className="mt-0.5 truncate text-[11.5px] text-ink/45 dark:text-fog/45">{ch.hub.autoReplyDm}</p>
              </div>
            </div>
          </article>
        </div>
      </section>

      {loading && <p className="text-[12px] text-ink/40 dark:text-fog/40">{ch.hub.loading}</p>}

      {confirmGoogleDisconnect && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label="Confirm Google disconnect"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
        >
          <div className="w-full max-w-md rounded-2xl border border-ink/[0.06] bg-white p-4 shadow-2xl dark:border-fog/[0.08] dark:bg-ink sm:p-5">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">{ch.hub.disconnectTitle}</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-ink/60 dark:text-fog/60">
              {ch.hub.disconnectDesc}
            </p>
            <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                onClick={() => setConfirmGoogleDisconnect(false)}
                disabled={googleBusy}
                className="rounded-lg border border-ink/10 px-3.5 py-2 text-[12px] font-semibold text-ink/70 dark:border-fog/10 dark:text-fog/70"
              >
                {t.common.cancel}
              </button>
              <button
                onClick={() => void disconnectGoogle()}
                disabled={googleBusy}
                className="rounded-lg bg-red-600 px-3.5 py-2 text-[12px] font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {googleBusy ? <LogoLoader size={14} /> : ch.hub.disconnectGoogle}
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
