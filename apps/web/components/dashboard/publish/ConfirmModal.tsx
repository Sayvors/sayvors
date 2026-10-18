"use client";

import { useEffect, useRef } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import { METHOD_META, type MediaState, type PostMethod, type PublishTarget } from "./types";

/*
 * The final gate before a post leaves the composer. UI-only today: the
 * confirm button says exactly that instead of faking a success state.
 * When the publish endpoint lands, "Publish now" wires up and the notice
 * disappears — the modal itself stays as the review step.
 */

export default function ConfirmModal({
  open,
  items,
  media,
  captionLen,
  descriptionLen,
  scheduled,
  onClose,
}: {
  open: boolean;
  items: { target: PublishTarget; methods: PostMethod[] }[];
  media: MediaState;
  captionLen: number;
  descriptionLen: number;
  scheduled: string | null;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const formatCount = items.reduce((n, i) => n + i.methods.length, 0);

  useEffect(() => {
    if (!open) return;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Review before publishing"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(0,0,0,0.45)] p-4"
    >
      <div className="w-full max-w-[420px] rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-5 shadow-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[16px] font-bold text-[var(--ui-ink)]">Review before publishing</h2>
            <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)]">
              {scheduled ? "This is a scheduled post (UI preview)." : "This is a preview edition (UI preview)."}
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close review"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[15px] font-bold text-[var(--ui-ink-2)] transition hover:bg-[var(--ui-sunken)] hover:text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
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

        <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2 text-[13px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            Keep editing
          </button>
          <button
            type="button"
            disabled
            title="Publishing wires up when the endpoint lands — this pass is UI-only"
            className="cursor-not-allowed rounded-[10px] bg-[var(--ui-ink)] px-4 py-2 text-[13px] font-semibold text-[var(--ui-on-ink)] opacity-50"
          >
            Publish now
          </button>
        </div>
      </div>
    </div>
  );
}
