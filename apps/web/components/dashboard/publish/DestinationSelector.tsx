"use client";

import Link from "next/link";
import PlatformMark from "@/components/channels/PlatformMark";
import GoogleBusinessLogo from "@/components/channels/GoogleBusinessLogo";
import { PLATFORM_META, PLATFORM_ORDER, type PlatformKey, type PublishTarget } from "./types";
import { Switch } from "./Switch";

/*
 * Destination picker for the unified Publish composer.
 *
 * Layout:
 *   1. Meta social destinations — "All connected" master switch + one row per
 *      connected asset. Rows check/uncheck individually; flipping the master
 *      selects or clears every Meta destination.
 *   2. Google Business Profile — master "All locations" toggle + one row per
 *      location. Google's only format is "post", so each location is a simple
 *      on/off destination (no format pills).
 *   3. Coming soon — muted chips for networks not yet offered.
 *
 * Every interactive row is a full-width tap target with a focus-visible ring
 * per AGENTS.md. No gradients — depth from hairlines + solid fills only.
 * Each platform badge carries its real brand colour (solid fill, no gradient).
 */

const BADGE_STYLE: Record<PlatformKey, string> = {
  whatsapp: "bg-[#eaffea] text-[#1ab35a]",
  facebook: "bg-[#eef3ff] text-[#1877f2]",
  instagram: "bg-[#fdeef6] text-[#c13584]",
  google_reviews: "bg-[#eef3ff] text-[#1a0dab]",
  x: "bg-[#f0f0f0] text-[#000000]",
  tiktok: "bg-[#fdeef2] text-[#fe2c55]",
  linkedin: "bg-[#eef3ff] text-[#0a66c2]",
  telegram: "bg-[#eef3ff] text-[#0088cc]",
  snapchat: "bg-[#fdfde9] text-[#fffc00]",
};

const SECTION_STYLE: Record<string, string> = {
  social: "bg-[#eef3ff] border-[#d8cbf5]",
  google: "bg-[#eef3ff] border-[#d8cbf5]",
};

export default function DestinationSelector({
  targets,
  status,
  allConnected,
  googleTargets,
  allGoogleConnected,
  selected,
  onSelectAll,
  onApplyAllGoogle,
  onToggleTarget,
  onToggleGoogleTarget,
}: {
  targets: PublishTarget[];
  status: "loading" | "ready" | "error";
  allConnected: boolean;
  googleTargets: PublishTarget[];
  allGoogleConnected: boolean;
  selected: Set<string>;
  onSelectAll: (v: boolean) => void;
  onApplyAllGoogle: (v: boolean) => void;
  onToggleTarget: (t: PublishTarget) => void;
  onToggleGoogleTarget: (t: PublishTarget) => void;
}) {
  const usable = targets.filter((t) => !t.demo && PLATFORM_META[t.platform]?.enabled);
  const comingSoon = PLATFORM_ORDER.filter((p) => !PLATFORM_META[p].enabled);

  if (status === "loading") {
    return (
      <div className="space-y-1.5" aria-hidden>
        <div className="h-9 animate-pulse rounded-[10px] bg-[var(--ui-sunken)]" />
        <div className="h-9 animate-pulse rounded-[10px] bg-[var(--ui-sunken)]" />
        <div className="h-9 animate-pulse rounded-[10px] bg-[var(--ui-sunken)]" />
      </div>
    );
  }

  if (usable.length === 0 && googleTargets.length === 0) {
    return (
      <div className="rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-5">
        <div className="flex flex-col items-center gap-2">
          <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">
            No channels connected
          </span>
          <p className="text-[13px] font-semibold text-[var(--ui-ink)]">
            Connect Facebook, Instagram, WhatsApp or Google Business Profile and they appear here.
          </p>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Link
            href="/dashboard/channels"
            className="rounded-[10px] bg-[var(--ui-ink)] px-3.5 py-1.5 text-[12px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            Connect channels
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* ── Meta social destinations ── */}
      {usable.length > 0 && (
        <section className="rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-3.5">
          <div className={SECTION_STYLE.social + " rounded-[10px] px-3 py-2.5 flex items-center justify-between"}>
            <div>
              <p className="text-[11px] font-bold uppercase tracking-widest text-[#1a0dab]">
                Social networks
              </p>
              <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
                Every live destination, always in sync with Channels.
              </p>
            </div>
            <Switch checked={allConnected} onChange={onSelectAll} label="" />
          </div>

          <ul className="mt-2 space-y-0.5">
            {usable.map((t) => {
              const checked = selected.has(t.id);
              const meta = PLATFORM_META[t.platform];
              return (
                <li key={t.id}>
                  <label
                    className={`flex min-w-0 cursor-pointer items-center gap-2.5 rounded-[10px] border px-3 py-2 transition ${
                      checked
                        ? "border-[var(--ui-ink)] bg-[var(--ui-ink)]/[0.06]"
                        : "border-[var(--ui-line)] bg-[var(--ui-surface)] hover:bg-[var(--ui-sunken)]"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggleTarget(t)}
                      className="h-4 w-4 shrink-0 accent-[var(--ui-ink)]"
                    />
                    <div className="flex min-w-0 items-center gap-2">
                      <PlatformMark platform={t.platform} size={16} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold text-[var(--ui-ink)]">{t.name}</span>
                        {t.handle && (
                          <span className="block truncate text-[11px] text-[var(--ui-ink-2)]">{t.handle}</span>
                        )}
                      </span>
                    </div>
                    <span className={`ml-auto shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${BADGE_STYLE[t.platform]}`}>
                      {meta.label}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {/* ── Google Business Profile locations ── */}
      {googleTargets.length > 0 && (
        <section className="rounded-[12px] border border-[#d8cbf5] bg-[#eef3ff] p-3.5">
          <div className="rounded-[10px] border border-[#d8cbf5] bg-[#ffffff] px-3 py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <GoogleBusinessLogo size={16} />
              <span className="text-[11px] font-bold uppercase tracking-widest text-[#1a0dab]">
                Google Business Profile
              </span>
            </div>
            <Switch checked={allGoogleConnected} onChange={onApplyAllGoogle} label="" />
          </div>

          <ul className="mt-2 space-y-0.5">
            {googleTargets.map((t) => {
              const checked = selected.has(t.id);
              return (
                <li key={t.id}>
                  <label
                    className={`flex min-w-0 cursor-pointer items-center gap-2.5 rounded-[10px] border px-3 py-2 transition ${
                      checked
                        ? "border-[#1a0dab] bg-[#eef3ff]"
                        : "border-[var(--ui-line)] bg-[var(--ui-surface)] hover:bg-[#eef3ff]"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onToggleGoogleTarget(t)}
                      className="h-4 w-4 shrink-0 accent-[#1a0dab]"
                    />
                    <div className="flex min-w-0 items-center gap-2">
                      <GoogleBusinessLogo size={16} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-semibold text-[var(--ui-ink)]">{t.name}</span>
                      </span>
                    </div>
                    <span className="ml-auto shrink-0 rounded-full bg-[#eef3ff] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[#1a0dab]">
                      Google
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {comingSoon.length > 0 && (
        <section className="rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">
              Coming soon
            </span>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {comingSoon.map((p: PlatformKey) => (
              <span
                key={p}
                title={`${PLATFORM_META[p].label} publishing lands later`}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 py-1 text-[11px] font-semibold text-[var(--ui-ink-2)] opacity-60"
              >
                <PlatformMark platform={p} size={14} />
                {PLATFORM_META[p].label}
              </span>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
