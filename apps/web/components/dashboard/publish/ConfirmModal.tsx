"use client";

import { useEffect, useRef } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import { METHOD_META, type MediaState, type PostMethod, type PublishTarget } from "./types";

/*
 * The final gate before a post leaves the composer. The confirm button
 * calls the real publish endpoint; while the request is in flight the
 * modal stays open and disabled, and a server error stays visible here
 * so nothing is lost behind a closed modal.
 */

export default function ConfirmModal({
  open,
  items,
  media,
  captionLen,
  descriptionLen,
  scheduled,
  busy,
  error,
  onConfirm,
  onClose,
}: {
  open: boolean;
  items: { target: PublishTarget; methods: PostMethod[] }[];
  media: MediaState;
  captionLen: number;
  descriptionLen: number;
  scheduled: string | null;
  busy: boolean;
  error: string | null;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const formatCount = items.reduce((n, i) => n + i.methods.length, 0);

  useEffect(() => {
    if (!open || busy) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Review before publishing"
      onClick={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(0,0,0,0.45)] p-4"
    >
      <div className="w-full max-w-[420px] rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[16px] font-bold text-[var(--ui-ink)]">Review before publishing</h2>
            <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
              {scheduled ? "This is a scheduled post." : "One push to every destination listed."}
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label="Close review"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[15px] font-bold text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-sunken)] hover:text-[var(--ui-ink)] disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            ×
          </button>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-[10px] bg-[var(--ui-sunken)] px-3 py-2.5">
          {media.type && (
            <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
              {media.type === "video" ? "Video" : "Image"}
            </span>
          )}
          <span className="text-[11px] font-semibold text-[var(--ui-ink-2)]">
            Caption {captionLen} · Description {descriptionLen}
          </span>
        </div>

        <p className="mt-3 px-1 text-[10px] font-bold uppercase tracking-widest text-[var(--ui-ink-2)]">
          {items.length === 0
            ? "No destination with a format selected"
            : `Publishing to ${items.length} destination${items.length === 1 ? "" : "s"} · ${formatCount} format${formatCount === 1 ? "" : "s"}`}
        </p>
        <ul className="mt-1.5 space-y-1">
          {items.map(({ target: t, methods }) => (
            <li key={t.id} className="flex items-center gap-2.5 rounded-[10px] border border-[var(--ui-line)] px-3 py-2">
              <PlatformMark platform={t.platform} size={16} />
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-[var(--ui-ink)]">{t.name}</span>
              <span className="shrink-0 text-right text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                {methods.map((m) => METHOD_META[m].label).join(" · ")}
              </span>
            </li>
          ))}
          {items.length === 0 && (
            <li className="px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink-2)]">
              Pick at least one destination and format before publishing.
            </li>
          )}
        </ul>

        <p aria-live="polite">
          {error && (
            <span role="alert" className="mt-3 block rounded-[10px] border border-red-500/50 bg-red-500/10 px-3 py-2 text-[12px] font-medium text-red-700 dark:text-red-400">
              {error}
            </span>
          )}
          {busy && !error && (
            <span role="status" className="mt-3 block px-1 text-[12px] font-semibold text-[var(--ui-ink-2)]">
              Publishing — this can take a few seconds…
            </span>
          )}
        </p>

        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2 text-[13px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            Keep editing
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || items.length === 0}
            className="rounded-[10px] bg-[var(--ui-ink)] px-5 py-2.5 text-[13px] font-semibold text-[var(--ui-on-ink)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            {busy ? "Publishing…" : scheduled ? "Schedule now" : "Publish now"}
          </button>
        </div>
      </div>
    </div>
  );
}
