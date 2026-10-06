"use client";

import { useEffect, useState } from "react";
import { fetchWhatsAppUsage, type WaUsage } from "@/lib/api-whatsapp-profile";
import { getProfile, updateResponseStyle, updateVoiceReplies } from "@/lib/api-profile";
import {
  ensureWhatsAppChannel,
  getAutoReply,
  updateAutoReply,
} from "@/lib/api-channels";

type SaveState = "idle" | "saving" | "saved" | "error";

const RESPONSE_STYLE_OPTIONS = [
  { value: "concise", label: "Concise", desc: "Clear, compact replies as a single message." },
  { value: "human", label: "Human-like", desc: "Natural short WhatsApp messages when appropriate." },
] as const;

const VOICE_REPLY_OPTIONS = [
  { value: "off", label: "Off", desc: "Never send voice notes — text only." },
  { value: "simple", label: "Simple", desc: "Short voice notes with clear built-in voices." },
  { value: "advanced", label: "Advanced", desc: "Short voice notes with premium AI voices." },
] as const;

const WA_FONT = { fontFamily: '"Segoe UI",Helvetica Neue,Helvetica,Arial,sans-serif' };

function StatusText({ state }: { state: SaveState }) {
  if (state === "saving") return <span className="text-[11px] text-[var(--wa-text-3)]">Saving&hellip;</span>;
  if (state === "saved")
    return (
      <span className="text-[11px] font-semibold text-[var(--wa-ok-text)]">Saved &mdash; applies to new messages</span>
    );
  if (state === "error")
    return <span className="text-[11px] font-semibold text-[var(--wa-danger)]">Couldn&rsquo;t save &mdash; try again</span>;
  return null;
}

function Card({ title, subtitle, children, status }: { title: string; subtitle: string; children: React.ReactNode; status?: SaveState }) {
  return (
    <section className="rounded-lg bg-[var(--wa-panel)] p-4 shadow-[0_1px_2px_rgba(0,0,0,0.15)]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[14px] font-bold text-[var(--wa-text)]">{title}</p>
        {status && <StatusText state={status} />}
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
          setAutoReply({ phoneId, enabled: !!cfg.enabled });
          setAutoReplyError(null);
        }
      } catch (e) {
        if (!dead) setAutoReplyError(e instanceof Error ? e.message : "Could not load auto-reply.");
      }
    })();
    return () => {
      dead = true;
    };
  }, [phoneId, phone, businessName]);

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
      {/* Messaging usage — the Sayvors plan quota */}
      <Card
        title="Messaging usage"
        subtitle="Your Sayvors plan includes a monthly pool of outbound WhatsApp messages. Resets on the 1st."
      >
        {usageError && (
          <p role="alert" className="mt-2 text-[12px] text-[var(--wa-danger)]">
            Could not load usage.{" "}
            <button className="font-semibold underline" onClick={() => { setUsageError(false); fetchWhatsAppUsage().then(setUsage).catch(() => setUsageError(true)); }}>
              Retry
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
              <span className="font-bold text-[var(--wa-text)]">{usage.used_this_month.toLocaleString()}</span> of{" "}
              {usage.monthly_limit.toLocaleString()} outbound messages this month ·{" "}
              {usage.plan === "pro" ? "Pro" : "Free"} plan
            </p>
          </div>
        )}
      </Card>

      {/* Auto-reply */}
      <Card title="Auto-reply" subtitle="Let the AI answer incoming WhatsApp messages automatically." status={autoReplyState}>
        {autoReplyError && <p role="alert" className="mt-2 text-[12px] text-[var(--wa-danger)]">{autoReplyError}</p>}
        {autoReplyReady === null && !autoReplyError && <p className="mt-2 text-[12px] text-[var(--wa-text-3)]">Loading&hellip;</p>}
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
            <span className="text-[13px] font-semibold text-[var(--wa-text)]">{autoReplyReady ? "On" : "Off"}</span>
          </button>
        )}
      </Card>

      {/* Response style */}
      <Card
        title="Response style"
        subtitle="How the AI's replies are delivered to customers on WhatsApp."
        status={styleState}
      >
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {RESPONSE_STYLE_OPTIONS.map((opt) => {
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
            ⚠️ Human-like responses may send multiple WhatsApp messages for a single response, which uses more of your monthly message pool.
          </div>
        )}
      </Card>

      {/* Voice replies */}
      <Card
        title="Voice replies"
        subtitle="When a customer seems confused, the AI can follow up with a short voice note in their own language."
        status={voiceState}
      >
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          {VOICE_REPLY_OPTIONS.map((opt) => {
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
            Voice notes are short (about 30&ndash;40 seconds) and sent at most once per reply. If a voice can&rsquo;t be produced, the customer gets the text reply instead.
          </p>
        )}
      </Card>
    </div>
  );
}
