"use client";

import Link from "next/link";
import { useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { PilotChannel, PilotState } from "@/lib/api-autopilot";

export default function AutoPilotDialog({
  channels,
  current,
  saving,
  error,
  onConfirm,
  onClose,
}: {
  channels: PilotChannel[];
  current: PilotState;
  saving: boolean;
  error: string | null;
  onConfirm: (on: boolean) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [selected, setSelected] = useState(current === "on");
  const hasChannels = channels.length > 0;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-ink/50 p-4 backdrop-blur-sm"
      onClick={() => {
        if (!saving) onClose();
      }}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t.pilot.dialogTitle}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape" && !saving) onClose();
        }}
        className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl dark:bg-ink"
      >
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-ink/[0.06] px-5 py-4 dark:border-fog/[0.08]">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-sm">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]" aria-hidden>
              <path d="M17.8 19.2L16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.2c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z" />
            </svg>
          </span>
          <div className="flex-1">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">{t.pilot.dialogTitle}</h2>
            <p className="text-[11px] text-ink/45 dark:text-fog/45">
              {channels.length === 1
                ? t.pilot.locationsOne
                : t.pilot.locationsMany.replace("{count}", String(channels.length))}
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            aria-label={t.pilot.close}
            className="rounded-lg p-1.5 text-ink/35 transition hover:bg-ink/[0.05] hover:text-ink disabled:opacity-40 dark:text-fog/40 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
              <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <div className="space-y-2.5 px-5 py-4">
          {/* ON option */}
          <button
            onClick={() => setSelected(true)}
            aria-pressed={selected}
            disabled={saving || !hasChannels}
            className={`flex w-full items-start gap-3 rounded-xl border-2 p-3.5 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-emerald/50 disabled:opacity-60 ${
              selected ? "border-emerald bg-emerald/[0.06]" : "border-ink/10 hover:border-emerald/50 dark:border-fog/10"
            }`}
          >
            <span className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-2 ${selected ? "border-emerald" : "border-ink/20 dark:border-fog/20"}`} aria-hidden>
              {selected && <span className="h-2 w-2 rounded-full bg-emerald" />}
            </span>
            <span>
              <span className="block text-[13px] font-bold text-ink dark:text-fog">
                {t.pilot.enableTitle}
              </span>
              <span className="mt-0.5 block text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
                {t.pilot.enableDesc}
              </span>
            </span>
          </button>

          {/* OFF option */}
          <button
            onClick={() => setSelected(false)}
            aria-pressed={!selected}
            disabled={saving || !hasChannels}
            className={`flex w-full items-start gap-3 rounded-xl border-2 p-3.5 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-amber/50 disabled:opacity-60 ${
              !selected ? "border-amber bg-amber/[0.07]" : "border-ink/10 hover:border-amber/60 dark:border-fog/10"
            }`}
          >
            <span className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border-2 ${!selected ? "border-amber" : "border-ink/20 dark:border-fog/20"}`} aria-hidden>
              {!selected && <span className="h-2 w-2 rounded-full bg-amber" />}
            </span>
            <span>
              <span className="block text-[13px] font-bold text-ink dark:text-fog">
                {t.pilot.manualTitle}
              </span>
              <span className="mt-0.5 block text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
                {t.pilot.manualDesc}
              </span>
            </span>
          </button>

          {!hasChannels && (
            <p className="rounded-lg bg-ink/[0.03] px-3 py-2.5 text-center text-[12px] text-ink/55 dark:bg-fog/[0.05] dark:text-fog/55">
              {t.pilot.noChannels}{" "}
              <Link href="/dashboard/channels" onClick={onClose} className="font-semibold text-deep-violet hover:underline">
                {t.pilot.connectFirst}
              </Link>
              .
            </p>
          )}

          {error && (
            <p role="alert" className="text-[12px] font-medium text-coral">{error}</p>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 border-t border-ink/[0.06] bg-ink/[0.015] px-5 py-3.5 dark:border-fog/[0.08] dark:bg-fog/[0.02]">
          <button
            onClick={onClose}
            disabled={saving}
            className="flex-1 rounded-lg border border-ink/10 px-4 py-2 text-[13px] font-semibold text-ink/60 transition hover:bg-ink/[0.03] disabled:opacity-40 dark:border-fog/10 dark:text-fog/60"
          >
            {t.common.cancel}
          </button>
          <button
            onClick={() => onConfirm(selected)}
            disabled={saving || !hasChannels}
            className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-deep-violet px-4 py-2 text-[13px] font-bold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
          >
            {saving ? (
              <>
                <LogoLoader size={16} /> {t.pilot.applying}
              </>
            ) : (
              t.pilot.apply
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
