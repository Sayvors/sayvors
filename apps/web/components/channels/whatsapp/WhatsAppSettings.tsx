"use client";

import { useEffect, useState } from "react";
import { QRCodeCanvas } from "qrcode.react";
import { fetchWhatsAppUsage, type WaUsage } from "@/lib/api-whatsapp-profile";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { getProfile, updateResponseStyle, updateVoiceReplies } from "@/lib/api-profile";
import {
  ensureWhatsAppChannel,
  getAutoReply,
  updateAutoReply,
} from "@/lib/api-channels";
import {
  createWhatsAppQrCode,
  deleteWhatsAppQrCode,
  fetchWhatsAppHealth,
  fetchWhatsAppQrCodes,
  type WhatsAppHealth,
  type WhatsAppQrCode,
} from "@/lib/api-whatsapp-tools";

type SaveState = "idle" | "saving" | "saved" | "error";

const WA_FONT = { fontFamily: '"Segoe UI",Helvetica Neue,Helvetica,Arial,sans-serif' };

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

function fmtNum(n: number, locale: string): string {
  return new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US", {
    maximumFractionDigits: 0,
  }).format(n);
}

function StatusText({ state, s }: { state: SaveState; s: { saving: string; saved: string; error: string } }) {
  if (state === "saving") return <span className="text-[11px] text-[var(--wa-text-3)]">{s.saving}</span>;
  if (state === "saved")
    return (
      <span className="text-[11px] font-semibold text-[var(--wa-ok-text)]">{s.saved}</span>
    );
  if (state === "error")
    return <span className="text-[11px] font-semibold text-[var(--wa-danger)]">{s.error}</span>;
  return null;
}

function Card({ title, subtitle, children, status, statusStrings }: { title: string; subtitle: string; children: React.ReactNode; status?: SaveState; statusStrings: { saving: string; saved: string; error: string } }) {
  return (
    <section className="rounded-lg bg-[var(--wa-panel)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.15)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[14px] font-bold text-[var(--wa-text)]">{title}</p>
        {status && <StatusText state={status} s={statusStrings} />}
      </div>
      <p className="mt-0.5 text-[12px] text-[var(--wa-text-2)]">{subtitle}</p>
      {children}
    </section>
  );
}

export default function WhatsAppSettings({
  phoneId,
  phone,
  businessName,
}: {
  phoneId: string;
  phone: string | null;
  businessName: string | null;
}) {
  const { t, locale } = useI18n();
  const s = t.dashboard.whatsapp.settings;
  const st = { saving: s.saving, saved: s.saved, error: s.error };
  // ── Usage (Sayvors plan quota — never Meta's messaging tier) ──
  const [usage, setUsage] = useState<WaUsage | null>(null);
  const [usageError, setUsageError] = useState(false);

  // ── Response style ──
  const [responseStyle, setResponseStyle] = useState<string>("concise");
  const [styleState, setStyleState] = useState<SaveState>("idle");

  // ── Voice replies ──
  const [voiceReplies, setVoiceReplies] = useState<string>("off");
  const [voiceState, setVoiceState] = useState<SaveState>("idle");

  // ── Auto-reply (per whatsapp channel row) ──
  // Keyed by phoneId: switching numbers shows Loading until the new channel's
  // config arrives, without resetting state synchronously inside the effect.
  const [autoReply, setAutoReply] = useState<{ phoneId: string; enabled: boolean } | null>(null);
  const [autoReplyState, setAutoReplyState] = useState<SaveState>("idle");
  const [autoReplyError, setAutoReplyError] = useState<string | null>(null);
  const [channelId, setChannelId] = useState<string | null>(null);

  // ── Number health + QR codes (Meta-side) ──
  const [health, setHealth] = useState<WhatsAppHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [qrCodes, setQrCodes] = useState<WhatsAppQrCode[]>([]);
  const [qrError, setQrError] = useState<string | null>(null);
  const [qrMessage, setQrMessage] = useState("");
  const [qrBusy, setQrBusy] = useState(false);

  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const [u, p] = await Promise.all([
          fetchWhatsAppUsage(),
          getProfile().catch(() => null),
        ]);
        if (dead) return;
        setUsage(u);
        if (p?.response_style) setResponseStyle(p.response_style);
        if (p?.voice_replies) setVoiceReplies(p.voice_replies);
      } catch {
        if (!dead) setUsageError(true);
      }
    })();
    return () => {
      dead = true;
    };
  }, []);

  // The Channel row may not exist until the first inbound message — resolve
  // (or transparently create) it here so the toggle can load its state.
  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const ch = await ensureWhatsAppChannel(phoneId, phone || businessName);
        const cfg = await getAutoReply(ch.id);
        if (!dead) {
          setChannelId(ch.id);
          setAutoReply({ phoneId, enabled: !!cfg.enabled });
          setAutoReplyError(null);
        }
      } catch (e) {
        if (!dead) setAutoReplyError(e instanceof Error ? e.message : s.errors.autoReply);
      }
    })();
    return () => {
      dead = true;
    };
  }, [phoneId, phone, businessName]);

  // Meta-side health and QR codes load once the channel row is resolved.
  useEffect(() => {
    if (!channelId) return;
    let dead = false;
    fetchWhatsAppHealth(channelId)
      .then((data) => { if (!dead) { setHealth(data); setHealthError(null); } })
      .catch((e) => { if (!dead) setHealthError(e instanceof Error ? e.message : s.errors.healthLoad); });
    fetchWhatsAppQrCodes(channelId)
      .then((rows) => { if (!dead) { setQrCodes(rows); setQrError(null); } })
      .catch((e) => { if (!dead) setQrError(e instanceof Error ? e.message : s.errors.qrLoad); });
    return () => { dead = true; };
  }, [channelId]);

  const createQr = async () => {
    if (!channelId || !qrMessage.trim() || qrBusy) return;
    setQrBusy(true);
    setQrError(null);
    try {
      const created = await createWhatsAppQrCode(channelId, qrMessage.trim());
      setQrCodes((prev) =>
        prev.some((qr) => qr.code === created.code)
          ? prev
          : [created, ...prev],
      );
      setQrMessage("");
    } catch (e) {
      setQrError(e instanceof Error ? e.message : s.errors.qrCreate);
    } finally {
      setQrBusy(false);
    }
  };

  const removeQr = async (code: string) => {
    if (!channelId || qrBusy) return;
    setQrBusy(true);
    setQrError(null);
    try {
      await deleteWhatsAppQrCode(channelId, code);
      setQrCodes((prev) => prev.filter((qr) => qr.code !== code));
    } catch (e) {
      setQrError(e instanceof Error ? e.message : s.errors.qrDelete);
    } finally {
      setQrBusy(false);
    }
  };

  const downloadQr = (qr: WhatsAppQrCode) => {
    // The canvas is drawn at 220px even though it is displayed small, so the
    // downloaded file prints cleanly at counter size.
    const canvas = document.getElementById(
      `qr-canvas-${qr.code}`,
    ) as HTMLCanvasElement | null;
    if (!canvas) return;
    const link = document.createElement("a");
    link.download = `whatsapp-qr-${qr.code}.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  };

  const chooseResponseStyle = async (style: string) => {
    if (style === responseStyle || styleState === "saving") return;
    const previous = responseStyle;
    setResponseStyle(style);
    setStyleState("saving");
    try {
      await updateResponseStyle(style);
      setStyleState("saved");
      setTimeout(() => setStyleState("idle"), 2500);
    } catch {
      setResponseStyle(previous);
      setStyleState("error");
      setTimeout(() => setStyleState("idle"), 4000);
    }
  };

  const chooseVoiceReplies = async (tier: string) => {
    if (tier === voiceReplies || voiceState === "saving") return;
    const previous = voiceReplies;
    setVoiceReplies(tier);
    setVoiceState("saving");
    try {
      await updateVoiceReplies(tier);
      setVoiceState("saved");
      setTimeout(() => setVoiceState("idle"), 2500);
    } catch {
      setVoiceReplies(previous);
      setVoiceState("error");
      setTimeout(() => setVoiceState("idle"), 4000);
    }
  };

  const autoReplyReady = autoReply?.phoneId === phoneId ? autoReply.enabled : null;

  const toggleAutoReply = async (next: boolean) => {
    if (autoReplyReady === null || autoReplyState === "saving") return;
    const previous = autoReplyReady;
    setAutoReply({ phoneId, enabled: next });
    setAutoReplyState("saving");
    try {
      const ch = await ensureWhatsAppChannel(phoneId, phone || businessName);
      await updateAutoReply(ch.id, { enabled: next });
      setAutoReplyState("saved");
      setTimeout(() => setAutoReplyState("idle"), 2500);
    } catch {
      setAutoReply({ phoneId, enabled: previous });
      setAutoReplyState("error");
      setTimeout(() => setAutoReplyState("idle"), 4000);
    }
  };

  const usedPct = usage ? Math.min(100, Math.round((usage.used_this_month / Math.max(1, usage.monthly_limit)) * 100)) : 0;

  return (
    <div className="space-y-3" style={WA_FONT}>
      <Card
        title={s.usageTitle}
        subtitle={s.usageSub}
        statusStrings={st}
      >
        {usageError && (
          <p role="alert" className="mt-2 text-[12px] text-[var(--wa-danger)]">
            {s.usageFail}{" "}
            <button className="font-semibold underline" onClick={() => { setUsageError(false); fetchWhatsAppUsage().then(setUsage).catch(() => setUsageError(true)); }}>
              {t.common.retry}
            </button>
          </p>
        )}
        {!usage && !usageError && (
          <div className="mt-3 animate-pulse">
            <div className="h-2 w-full rounded bg-[var(--wa-track)]" />
            <div className="mt-2 h-3 w-1/2 rounded bg-[var(--wa-track)]" />
          </div>
        )}
        {usage && (
          <div className="mt-3">
            <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--wa-track)]">
              <div
                className={`h-full rounded-full transition-all ${usedPct >= 90 ? "bg-red-500" : usedPct >= 70 ? "bg-amber-500" : "bg-[var(--wa-accent)]"}`}
                style={{ width: `${Math.max(2, usedPct)}%` }}
                role="progressbar"
                aria-valuenow={usedPct}
                aria-valuemin={0}
                aria-valuemax={100}
              />
            </div>
            <p className="mt-2 text-[12px] text-[var(--wa-text-2)]">
              {fill(s.outOf, {
                used: fmtNum(usage.used_this_month, locale),
                limit: fmtNum(usage.monthly_limit, locale),
                plan: usage.plan === "pro" ? "Pro" : usage.plan === "free-trial" ? "Free Trial" : "Free",
              })}
            </p>
          </div>
        )}
      </Card>

      {/* Number health — Meta's quality rating and sending capacity */}
      <Card
        title={s.healthTitle}
        subtitle={s.healthSub}
        statusStrings={st}
      >
        {healthError && (
          <p role="alert" className="mt-2 text-[12px] text-[var(--wa-danger)]">{healthError}</p>
        )}
        {!health && !healthError && <p className="mt-2 text-[12px] text-[var(--wa-text-3)]">{s.healthLoading}</p>}
        {health && (
          <dl className="mt-3 grid gap-2 sm:grid-cols-2">
            {[
              { label: s.healthFields.verifiedName, value: health.verified_name || "—" },
              { label: s.healthFields.number, value: health.display_phone_number || "—" },
              { label: s.healthFields.quality, value: health.quality_rating || "—" },
              { label: s.healthFields.limit, value: health.messaging_limit_tier || "—" },
              { label: s.healthFields.status, value: health.status || "—" },
              { label: s.healthFields.verification, value: health.code_verification_status || "—" },
            ].map((row) => (
              <div key={row.label} className="rounded-[8px] bg-[var(--wa-panel-2,rgba(0,0,0,0.03))] px-3 py-2">
                <dt className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--wa-text-3)]">{row.label}</dt>
                <dd className={`mt-0.5 text-[13px] font-semibold ${
                  row.label === s.healthFields.quality && row.value === "RED"
                    ? "text-[var(--wa-danger)]"
                    : "text-[var(--wa-text)]"
                }`}>{row.value}</dd>
              </div>
            ))}
          </dl>
        )}
      </Card>

      {/* QR codes — a zero-cost WhatsApp entry point for counters and print */}
      <Card
        title={s.qrTitle}
        subtitle={s.qrSub}
        statusStrings={st}
      >
        {qrError && <p role="alert" className="mt-2 text-[12px] text-[var(--wa-danger)]">{qrError}</p>}
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            value={qrMessage}
            onChange={(e) => setQrMessage(e.target.value)}
            maxLength={140}
            placeholder={s.qrPh}
            aria-label={s.qrAria}
            className="min-w-0 flex-1 rounded-[8px] border border-[var(--wa-line,rgba(0,0,0,0.12))] bg-white px-3 py-2 text-[13px] text-[var(--wa-text)] outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--wa-accent)]"
          />
          <button
            onClick={createQr}
            disabled={qrBusy || !qrMessage.trim()}
            className="rounded-[8px] bg-[var(--wa-accent)] px-4 py-2 text-[12px] font-bold text-white disabled:opacity-50"
          >
            {qrBusy ? s.working : s.createQr}
          </button>
        </div>
        <p className="mt-1 text-[11px] text-[var(--wa-text-3)]">{fill(s.chars, { count: qrMessage.length })}</p>
        {qrCodes.length === 0 ? (
          <p className="mt-3 text-[12px] text-[var(--wa-text-3)]">{s.noQr}</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {qrCodes.map((qr) => (
              <li key={qr.code} className="flex items-start gap-3 rounded-[8px] bg-[var(--wa-panel-2,rgba(0,0,0,0.03))] px-3 py-2">
                <QRCodeCanvas
                  id={`qr-canvas-${qr.code}`}
                  value={qr.deep_link_url}
                  size={220}
                  bgColor="#ffffff"
                  fgColor="#14101F"
                  level="M"
                  aria-label={fill(s.qrAlt, { msg: qr.prefilled_message })}
                  className="h-16 w-16 shrink-0 rounded bg-white p-1"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] font-semibold text-[var(--wa-text)]">{qr.prefilled_message}</p>
                  <a
                    href={qr.deep_link_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-0.5 block truncate text-[11px] text-[var(--wa-accent)] underline"
                  >
                    {qr.deep_link_url}
                  </a>
                </div>
                <button
                  onClick={() => downloadQr(qr)}
                  disabled={qrBusy}
                  className="shrink-0 text-[11px] font-semibold text-[var(--wa-accent)] underline disabled:opacity-50"
                >
                  {s.download}
                </button>
                <button
                  onClick={() => removeQr(qr.code)}
                  disabled={qrBusy}
                  title={s.removeTitle}
                  className="shrink-0 text-[11px] font-semibold text-[var(--wa-text-3)] underline disabled:opacity-50"
                >
                  {s.remove}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Auto-reply */}
      <Card title={s.autoTitle} subtitle={s.autoSub} status={autoReplyState} statusStrings={st}>
        {autoReplyError && <p role="alert" className="mt-2 text-[12px] text-[var(--wa-danger)]">{autoReplyError}</p>}
        {autoReplyReady === null && !autoReplyError && <p className="mt-2 text-[12px] text-[var(--wa-text-3)]">{s.loading}</p>}
        {autoReplyReady !== null && (
          <button
            onClick={() => toggleAutoReply(!autoReplyReady)}
            disabled={autoReplyState === "saving"}
            role="switch"
            aria-checked={autoReplyReady}
            className="mt-3 flex items-center gap-3 disabled:opacity-60"
          >
            <span className={`relative h-6 w-11 rounded-full transition ${autoReplyReady ? "bg-[var(--wa-accent)]" : "bg-[var(--wa-track)]"}`}>
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${autoReplyReady ? "left-[22px]" : "left-0.5"}`} />
            </span>
            <span className="text-[13px] font-semibold text-[var(--wa-text)]">{autoReplyReady ? s.on : s.off}</span>
          </button>
        )}
      </Card>

      {/* Response style */}
      <Card
        title={s.styleTitle}
        subtitle={s.styleSub}
        status={styleState}
        statusStrings={st}
      >
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {[
            { value: "concise", label: s.concise, desc: s.conciseDesc },
            { value: "human", label: s.human, desc: s.humanDesc },
          ].map((opt) => {
            const selected = responseStyle === opt.value;
            return (
              <button
                key={opt.value}
                onClick={() => chooseResponseStyle(opt.value)}
                disabled={styleState === "saving"}
                aria-pressed={selected}
                className={`rounded-lg border px-3 py-2 text-left transition disabled:opacity-60 ${
                  selected ? "border-[var(--wa-accent)] bg-[var(--wa-accent)]/[0.06]" : "border-[var(--wa-border)] hover:border-[var(--wa-accent)]/40"
                }`}
              >
                <span className="block text-[12px] font-semibold text-[var(--wa-text)]">{opt.label}</span>
                <span className="mt-0.5 block text-[11px] text-[var(--wa-text-3)]">{opt.desc}</span>
              </button>
            );
          })}
        </div>
        {responseStyle === "human" && (
          <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/[0.06] px-3 py-2 text-[11px] leading-relaxed text-[var(--wa-warn-text)]">
            {s.humanWarn}
          </div>
        )}
      </Card>

      {/* Voice replies */}
      <Card
        title={s.voiceTitle}
        subtitle={s.voiceSub}
        status={voiceState}
        statusStrings={st}
      >
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          {[
            { value: "off", label: s.voiceOff, desc: s.voiceOffDesc },
            { value: "simple", label: s.voiceSimple, desc: s.voiceSimpleDesc },
            { value: "advanced", label: s.voiceAdvanced, desc: s.voiceAdvancedDesc },
          ].map((opt) => {
            const selected = voiceReplies === opt.value;
            return (
              <button
                key={opt.value}
                onClick={() => chooseVoiceReplies(opt.value)}
                disabled={voiceState === "saving"}
                aria-pressed={selected}
                className={`rounded-lg border px-3 py-2 text-left transition disabled:opacity-60 ${
                  selected ? "border-[var(--wa-accent)] bg-[var(--wa-accent)]/[0.06]" : "border-[var(--wa-border)] hover:border-[var(--wa-accent)]/40"
                }`}
              >
                <span className="block text-[12px] font-semibold text-[var(--wa-text)]">{opt.label}</span>
                <span className="mt-0.5 block text-[11px] text-[var(--wa-text-3)]">{opt.desc}</span>
              </button>
            );
          })}
        </div>
        {voiceReplies !== "off" && (
          <p className="mt-2 text-[11px] leading-relaxed text-[var(--wa-text-3)]">
            {s.voiceNote}
          </p>
        )}
      </Card>
    </div>
  );
}
