"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import {
  PILL_META,
  notifyPill,
  subscribePills,
  type PillData,
  type PillKind,
} from "@/lib/notifications";

declare global {
  interface Window {
    __sayvorsPill?: (text: string, kind: PillKind) => void;
  }
}

type Stage = "dot" | "open" | "closing";

const DOT_MS = 520;
const HOLD_MS = 4000;
const EXIT_MS = 420;

const GOOGLE_CONIC =
  "conic-gradient(from 0deg, #4285F4, #EA4335, #FBBC05, #34A853, #4285F4)";

/** Google "G" in official brand colors. */
function GoogleG({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <path
        fill="#4285F4"
        d="M23.5 12.27c0-.85-.08-1.66-.22-2.45H12v4.64h6.45c-.28 1.48-1.12 2.73-2.36 3.58v3h3.86c2.26-2.09 3.55-5.16 3.55-8.77z"
      />
      <path
        fill="#34A853"
        d="M12 24c3.24 0 5.96-1.07 7.94-2.91l-3.86-3c-1.08.72-2.45 1.15-4.08 1.15-3.13 0-5.78-2.11-6.73-4.96H1.29v3.1C3.26 21.3 7.31 24 12 24z"
      />
      <path
        fill="#FBBC05"
        d="M5.27 14.28A7.2 7.2 0 0 1 4.89 12c0-.78.14-1.53.38-2.28V6.62H1.29A12 12 0 0 0 0 12c0 1.93.46 3.76 1.29 5.38l3.98-3.1z"
      />
      <path
        fill="#EA4335"
        d="M12 4.77c1.76 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.31 0 3.26 2.7 1.29 7.08l3.98 3.1c.95-2.85 3.6-4.96 6.73-4.96z"
      />
    </svg>
  );
}

function ToastPill({ pill, onDone }: { pill: PillData; onDone: (id: string) => void }) {
  const [stage, setStage] = useState<Stage>("dot");

  useEffect(() => {
    const t1 = window.setTimeout(() => setStage("open"), DOT_MS);
    const t2 = window.setTimeout(() => setStage("closing"), DOT_MS + HOLD_MS);
    const t3 = window.setTimeout(() => onDone(pill.id), DOT_MS + HOLD_MS + EXIT_MS);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
      window.clearTimeout(t3);
    };
  }, [pill.id, onDone]);

  const meta = PILL_META[pill.kind];

  if (stage === "dot") {
    return (
      <div className="sayvors-dot-enter h-4 w-4 rounded-full shadow-lg" style={{ background: GOOGLE_CONIC }} aria-hidden />
    );
  }

  return (
    <div
      role="status"
      className={`flex max-w-md origin-top items-center gap-2.5 rounded-full border border-white/15 bg-ink/90 py-2 pl-2.5 pr-4 shadow-2xl backdrop-blur-xl dark:border-white/10 dark:bg-black/85 ${meta.glow} ${
        stage === "closing" ? "sayvors-pill-exit" : "sayvors-pill-expand"
      }`}
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-white shadow">
        <GoogleG className="h-5 w-5" />
      </span>
      <span className="min-w-0">
        <span className="block truncate text-[12.5px] font-semibold text-white">
          {pill.text}
        </span>
        <span className="block text-[10px] font-medium uppercase tracking-wider text-white/50">
          {meta.label} · Sayvors
        </span>
      </span>
    </div>
  );
}

interface ToastContextValue {
  /** Show a reminder pill (also available via `notifyPill` without context). */
  pushPill: (text: PillData["text"], kind: PillData["kind"]) => void;
}

const ToastContext = createContext<ToastContextValue>({ pushPill: () => {} });

export function useToast() {
  return useContext(ToastContext);
}

export default function ToastProvider({ children }: { children: React.ReactNode }) {
  const [pills, setPills] = useState<PillData[]>([]);

  const dismiss = useCallback((id: string) => {
    setPills((prev) => prev.filter((p) => p.id !== id));
  }, []);

  const push = useCallback((pill: PillData) => {
    setPills((prev) => {
      if (prev.some((p) => p.id === pill.id)) return prev;
      return [...prev, pill].slice(-3);
    });
  }, []);

  useEffect(() => subscribePills(push), [push]);

  const pushPill = useCallback(
    (text: string, kind: PillData["kind"]) =>
      push({ id: `${Date.now()}-${Math.random()}`, kind, text }),
    [push]
  );

  // Dev-only simulator hook: open DevTools console and run
  // __sayvorsPill("New ★5 review from Adeel", "pulled")
  // __sayvorsPill("Auto-reply failed for ★2 review", "failed")
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") {
      window.__sayvorsPill = (text: string, kind: PillKind) => notifyPill(text, kind);
      return () => {
        delete window.__sayvorsPill;
      };
    }
  }, []);

  return (
    <ToastContext.Provider value={{ pushPill }}>
      {children}
      {/* Reminder pills — decorative only, never intercept clicks */}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 top-6 z-[80] flex flex-col items-center gap-2 px-4">
        <style>{`
          @keyframes sayvors-dot-in {
            0% { transform: translateY(-180%) scale(0.3); opacity: 0; }
            60% { transform: translateY(4%) scale(1.08); opacity: 1; }
            100% { transform: translateY(0) scale(1); opacity: 1; }
          }
          @keyframes sayvors-open-expand {
            0% { transform: scaleY(0.15) scaleX(0.55) translateY(-6px); opacity: 0.2; }
            60% { transform: scaleY(1.04) scaleX(1.01) translateY(0); opacity: 1; }
            100% { transform: scaleY(1) scaleX(1) translateY(0); opacity: 1; }
          }
          @keyframes sayvors-pill-exit {
            0% { transform: scaleY(1) translateY(0); opacity: 1; }
            100% { transform: scaleY(0.15) translateY(-70%); opacity: 0; }
          }
          .sayvors-dot-enter { animation: sayvors-dot-in 0.52s cubic-bezier(0.22, 1.2, 0.36, 1) both; }
          .sayvors-pill-expand { animation: sayvors-open-expand 0.38s cubic-bezier(0.22, 1.2, 0.36, 1) both; }
          .sayvors-pill-exit { animation: sayvors-pill-exit 0.42s cubic-bezier(0.5, 0, 0.75, 0) both; }
          @media (prefers-reduced-motion: reduce) {
            .sayvors-dot-enter, .sayvors-pill-expand, .sayvors-pill-exit { animation-duration: 0.01s; }
          }
        `}</style>
        {pills.map((p) => (
          <ToastPill key={p.id} pill={p} onDone={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
