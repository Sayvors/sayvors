"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";
import {
  CONNECT_IMPORT_EVENT,
  CONNECT_IMPORT_STORAGE_KEY,
  clearActiveConnectImport,
  dismissConnectImport,
  isConnectImportDismissed,
} from "@/lib/connect-import";
import ConnectImportModal, { type ImportSession } from "./ConnectImportModal";

function progressPercent(session: ImportSession): number {
  if (session.status === "completed") return 100;
  if (session.status === "ready" || session.status === "publishing" || session.status === "awaiting_scope") {
    return 100;
  }
  if (session.status === "generating") {
    const total = session.progress.total_drafts || 0;
    if (!total) return 8;
    return Math.min(
      100,
      Math.round(
        ((session.progress.drafts_ready + session.progress.drafts_failed) / total) * 100,
      ),
    );
  }
  const total = session.progress.total_reviews || 0;
  if (!total) return 8;
  return Math.min(100, Math.round((session.progress.fetched_reviews / total) * 100));
}

export default function ConnectImportLauncher() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const read = () => {
      const stored = window.localStorage.getItem(CONNECT_IMPORT_STORAGE_KEY);
      if (stored) setSessionId(stored);
    };
    read();
    const onCustom = (event: Event) => {
      const detail = (event as CustomEvent<{ sessionId?: string | null }>).detail;
      setSessionId(detail?.sessionId ?? null);
      if (detail?.sessionId) setOpen(true);
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === CONNECT_IMPORT_STORAGE_KEY) read();
    };
    window.addEventListener(CONNECT_IMPORT_EVENT, onCustom);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(CONNECT_IMPORT_EVENT, onCustom);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const latestQuery = useQuery({
    queryKey: ["connect-import-latest"],
    queryFn: async () =>
      (await apiFetch("/api/v1/channels/google/import-sessions/latest")) as {
        session: ImportSession | null;
      },
    enabled: !sessionId,
    // Idle tabs were polling every 5s forever (12 req/min/tab); 20s still
    // auto-opens a fresh import from another tab without flooding the logs.
    refetchInterval: 20000,
  });

  useEffect(() => {
    const latest = latestQuery.data?.session;
    // Only auto-open work that is actually moving. A "ready" session is
    // waiting on the merchant, and a dismissed one was closed on purpose —
    // the 20s poll must not resurrect either.
    if (
      latest &&
      ["queued", "fetching", "generating", "publishing"].includes(latest.status) &&
      !isConnectImportDismissed(latest.id)
    ) {
      setSessionId(latest.id);
      setOpen(true);
    }
  }, [latestQuery.data?.session]);

  const query = useQuery({
    queryKey: ["connect-import-launcher", sessionId],
    queryFn: async () =>
      (await apiFetch(`/api/v1/channels/google/import-sessions/${sessionId}`)) as ImportSession,
    enabled: !!sessionId,
    refetchInterval: (queryState) => {
      const data = queryState.state.data as ImportSession | undefined;
      if (!data) return 3000;
      return ["completed", "failed", "ready"].includes(data.status) ? false : 2500;
    },
  });
  const session = query.data ?? null;

  // Closing is final. Remember it so the 20s latest-session poll cannot pop
  // the modal back up, and drop the launcher entirely unless work is still
  // running (the floating progress pill stays for that case).
  const handleClose = () => {
    if (sessionId) dismissConnectImport(sessionId);
    const running = session
      ? ["queued", "fetching", "generating", "publishing"].includes(session.status)
      : false;
    if (!running) {
      clearActiveConnectImport();
      setSessionId(null);
    }
    setOpen(false);
  };

  useEffect(() => {
    if (query.isError) {
      // A deleted or expired session must not leave a dead button forever.
      clearActiveConnectImport();
      setSessionId(null);
    }
  }, [query.isError]);

  useEffect(() => {
    if (
      session &&
      ["completed", "failed"].includes(session.status) &&
      !open
    ) {
      clearActiveConnectImport();
      setSessionId(null);
    }
  }, [session, open]);

  if (!sessionId) return null;

  if (!session) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed right-4 top-1/2 z-[60] -translate-y-1/2 rounded-full border border-ink/10 bg-white px-3 py-2 text-[11px] font-bold text-ink/55 shadow-[0_8px_24px_rgba(20,16,31,0.12)]"
        aria-label="Open Google import progress"
      >
        Importing…
      </button>
    );
  }

  if (session.status === "completed" || session.status === "failed") {
    return open ? (
      <ConnectImportModal
        sessionId={sessionId}
        onClose={handleClose}
      />
    ) : null;
  }

  const pct = progressPercent(session);
  const circumference = 2 * Math.PI * 18;
  const offset = circumference - (pct / 100) * circumference;
  const label =
    session.status === "awaiting_scope"
      ? "Setup"
      : session.status === "ready"
        ? "Review drafts"
        : session.status === "publishing"
          ? "Publishing"
          : "Importing";

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="fixed right-4 top-1/2 z-[60] flex -translate-y-1/2 flex-col items-center gap-1 rounded-[28px] border border-ink/10 bg-white p-2 shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_10px_30px_rgba(20,16,31,0.14)] transition active:translate-y-[calc(-50%+2px)] active:scale-[0.98]"
        aria-label={`Open Google import progress: ${label}, ${pct}%`}
      >
        <span className="relative flex h-12 w-12 items-center justify-center">
          <svg viewBox="0 0 44 44" className="absolute inset-0 h-12 w-12 -rotate-90">
            <circle cx="22" cy="22" r="18" fill="none" stroke="rgba(20,16,31,0.08)" strokeWidth="4" />
            <circle
              cx="22"
              cy="22"
              r="18"
              fill="none"
              stroke="#3D1D6E"
              strokeWidth="4"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={offset}
              className="transition-all duration-500"
            />
          </svg>
          <span className="text-[10px] font-bold tabular-nums text-deep-violet">{pct}%</span>
        </span>
        <span className="max-w-[68px] truncate text-[9px] font-bold text-ink/50">{label}</span>
      </button>
      {open && (
        <ConnectImportModal
          sessionId={sessionId}
          onClose={handleClose}
        />
      )}
    </>
  );
}
