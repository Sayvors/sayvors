"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  subtitle?: string;
  labelledBy?: string;
  width?: string;
  busy?: boolean;
  closeLabel?: string;
  children: ReactNode;
}

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, summary, [tabindex]:not([tabindex="-1"])';
// Nested dialogs share one document-level keyboard listener. Only the topmost
// panel may handle Escape/Tab, and scrolling stays locked until the last closes.
const MODAL_STACK: HTMLElement[] = [];
let bodyOverflowBeforeModal = "";

export default function Modal({ open, onClose, title, subtitle, labelledBy, width = "max-w-[600px]", busy, closeLabel = "Close", children }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const prevFocus = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  const busyRef = useRef(busy);
  const titleId = useId();
  const subtitleId = useId();

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    if (!open) return;
    prevFocus.current = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    if (!panel) return;
    MODAL_STACK.push(panel);
    if (MODAL_STACK.length === 1) {
      bodyOverflowBeforeModal = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }
    const focusables = () => Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = focusables()[0];
    (first ?? panel)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (MODAL_STACK[MODAL_STACK.length - 1] !== panel) return;
      if (e.key === "Escape") {
        if (!busyRef.current) onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const list = focusables();
      if (!list.length) return;
      const active = document.activeElement as HTMLElement | null;
      const idx = list.indexOf(active ?? list[0]);
      if (e.shiftKey) {
        if (idx <= 0) { list[list.length - 1].focus(); e.preventDefault(); }
      } else {
        if (idx === list.length - 1) { list[0].focus(); e.preventDefault(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      const index = MODAL_STACK.lastIndexOf(panel);
      if (index >= 0) MODAL_STACK.splice(index, 1);
      if (MODAL_STACK.length === 0) {
        document.body.style.overflow = bodyOverflowBeforeModal;
      }
      prevFocus.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/45 p-4"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy ?? (title ? titleId : undefined)}
        aria-describedby={subtitle ? subtitleId : undefined}
        tabIndex={-1}
        className={`flex max-h-[92vh] w-full ${width} flex-col overflow-hidden rounded-[8px] bg-white shadow-[0_40px_80px_-40px_rgba(20,16,31,0.55)] ring-1 ring-ink/[0.08] outline-none dark:bg-[#1b1530] dark:ring-white/[0.08]`}
      >
        {(title || subtitle) && (
          <div className="flex items-start justify-between gap-3 border-b border-ink/[0.06] px-6 py-5 dark:border-white/[0.08]">
            <div className="min-w-0">
              {title && <h2 id={titleId} className="text-[17px] font-bold text-ink dark:text-fog">{title}</h2>}
              {subtitle && <p id={subtitleId} className="mt-0.5 text-[12px] text-ink/70 dark:text-fog/70">{subtitle}</p>}
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              aria-label={closeLabel}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[16px] font-bold text-ink/45 transition hover:bg-ink/[0.05] hover:text-ink disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:text-fog/45"
            >
              ×
            </button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {children}
        </div>
      </div>
    </div>
  );
}
