"use client";

import Link from "next/link";
import PlatformMark from "@/components/channels/PlatformMark";
import { PLATFORM_META, PLATFORM_ORDER, type PlatformKey, type PublishTarget } from "./types";
import { Switch } from "./Switch";

/*
 * Destination picker for the unified Publish composer.
 *
 * One "all connected" master switch on top, then one row per connected
 * asset with its own checkbox. Rows the backend can't serve yet (X,
 * TikTok, …) sit in a disabled "coming soon" group so the roadmap reads
 * through the UI without pretending buttons exist.
 */

export default function DestinationSelector({
  targets,
  status,
  allConnected,
  selected,
  onSelectAll,
  onToggleTarget,
  onLoadDemo,
}: {
  targets: PublishTarget[];
  status: "loading" | "ready" | "error";
  allConnected: boolean;
  selected: Set<string>;
  onSelectAll: (v: boolean) => void;
  onToggleTarget: (t: PublishTarget) => void;
  onLoadDemo: () => void;
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

  if (usable.length === 0) {
    return (
      <div className="rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-4">
        <p className="text-[13px] font-semibold text-[var(--ui-ink)]">No channel is connected yet</p>
        <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">
          Connect Facebook, Instagram or WhatsApp and they appear here as publish destinations.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Link
            href="/dashboard/channels"
            className="rounded-[10px] bg-[var(--ui-ink)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            Connect channels
          </Link>
          <button
            type="button"
            onClick={onLoadDemo}
            className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-line)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            Preview with sample channels
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-3.5 py-2.5">
        <div>
          <p className="text-[13px] font-semibold text-[var(--ui-ink)]">All connected</p>
          <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
            Every live destination, always in sync with Channels.
          </p>
        </div>
        <Switch checked={allConnected} onChange={onSelectAll} label="" />
      </div>

      <ul className="mt-2 space-y-1.5">
        {usable.map((t) => {
          const checked = selected.has(t.id);
          const meta = PLATFORM_META[t.platform];
          return (
            <li key={t.id}>
              <label
                className={`flex cursor-pointer items-center gap-2.5 rounded-[10px] border px-3 py-2 transition ${
                  checked
                    ? "border-[var(--ui-ink)] bg-[var(--ui-ink)]/[0.045]"
                    : "border-[var(--ui-line)] bg-[var(--ui-surface)] hover:bg-[var(--ui-sunken)]"
                }`}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggleTarget(t)}
                  className="h-4 w-4 shrink-0 accent-[var(--ui-ink)]"
                />
                <PlatformMark platform={t.platform} size={18} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-semibold text-[var(--ui-ink)]">{t.name}</span>
                  {t.handle && <span className="block truncate text-[11px] text-[var(--ui-ink-2)]">{t.handle}</span>}
                </span>
                <span className="shrink-0 rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                  {meta.label}
                </span>
              </label>
            </li>
          );
        })}
      </ul>

      {comingSoon.length > 0 && (
        <div className="mt-3">
          <p className="px-1 pb-1.5 text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">
            Coming soon
          </p>
          <div className="flex flex-wrap gap-1.5">
            {comingSoon.map((p: PlatformKey) => (
              <span
                key={p}
                title={`${PLATFORM_META[p].label} publishing lands later`}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 py-1 text-[11px] font-semibold text-[var(--ui-ink-2)] opacity-70"
              >
                <PlatformMark platform={p} size={14} />
                {PLATFORM_META[p].label}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
