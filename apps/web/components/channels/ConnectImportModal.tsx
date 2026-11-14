"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api-rag";
import { clearActiveConnectImport } from "@/lib/connect-import";

export type ImportItem = {
  id: string;
  channel_id: string;
  review_id: string;
  location_name: string | null;
  reviewer_name: string | null;
  rating: number;
  review_text: string | null;
  review_time: string | null;
  status: string;
  reply_id: string | null;
  draft_text: string | null;
  selected: boolean;
  error: string | null;
};

export type ImportLocation = {
  channel_id: string;
  name: string;
  address: string | null;
  status: string;
  items: ImportItem[];
};

export type ImportEvent = {
  id: string;
  level: string;
  message: string;
  created_at: string | null;
};

export type ImportSummary = {
  reviews_total: number;
  unanswered_before: number;
  published_now: number;
  already_answered: number;
  failed: number;
  business_age_months: number | null;
  review_volume: { month: string; count: number }[];
  rating_scatter: { date: string; rating: number }[];
  analytics_url: string;
};

export type ImportSession = {
  id: string;
  status: string;
  scope_days: number;
  progress: {
    total_locations: number;
    fetched_locations: number;
    total_reviews: number;
    fetched_reviews: number;
    total_drafts: number;
    drafts_ready: number;
    drafts_failed: number;
  };
  locations: ImportLocation[];
  events?: ImportEvent[];
  summary: ImportSummary | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
};

type Filter = "all" | "needs_reply" | "draft_ready" | "already_replied" | "failed";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "needs_reply", label: "Needs reply" },
  { id: "draft_ready", label: "Draft ready" },
  { id: "already_replied", label: "Already replied" },
  { id: "failed", label: "Failed" },
];

const SCOPES = [
  { days: 30, label: "Last 30 days" },
  { days: 180, label: "Last 6 months" },
  { days: 365, label: "Last 12 months" },
  { days: 0, label: "All time" },
];

const ACTIVE_STATUSES = ["queued", "fetching", "awaiting_scope", "generating", "ready", "publishing"];

// Guided stage strip: the user sees the whole journey one step at a time,
// even when a step has zero items (fresh account / no reviews yet).
const STAGES = [
  { id: "connected", label: "Connected" },
  { id: "fetching", label: "Fetching history" },
  { id: "drafting", label: "Drafting replies" },
  { id: "publishing", label: "Publishing" },
] as const;

function stageIndexFor(status: string): number {
  if (status === "publishing" || status === "completed") return 3;
  if (status === "ready") return 2;
  if (status === "generating" || status === "awaiting_scope") return 2;
  if (status === "fetching" || status === "queued") return 1;
  return 0;
}

function StageSteps({ status }: { status: string }) {
  const current = stageIndexFor(status);
  const done = status === "completed";
  return (
    <ol className="mt-4 flex items-center gap-1 overflow-x-auto">
      {STAGES.map((stage, i) => {
        const active = i === current && !done;
        const reached = done || i <= current;
        return (
          <li key={stage.id} className="flex min-w-0 items-center gap-1">
            {i > 0 && <span className="h-px w-4 shrink-0 bg-ink/15" aria-hidden />}
            <span
              className={`flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[10.5px] font-bold uppercase tracking-wide ${
                reached ? "bg-emerald-100 text-emerald-700" : "bg-ink/[0.06] text-ink/45"
              } ${active ? "ring-2 ring-emerald-400/50" : ""}`}
            >
              <span aria-hidden>{done || i < current ? "✓" : i === current ? "●" : "○"}</span>
              <span className="whitespace-nowrap">{stage.label}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function itemMatches(item: ImportItem, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "needs_reply") {
    return ["pending", "generating", "outside_scope"].includes(item.status);
  }
  if (filter === "draft_ready") return item.status === "draft_ready";
  if (filter === "already_replied") return item.status === "already_replied";
  return ["failed", "publish_failed"].includes(item.status);
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "Queued",
    generating: "Writing reply",
    draft_ready: "Reply ready",
    already_replied: "Already replied",
    outside_scope: "Outside selected range",
    failed: "Needs another try",
    published: "Posted",
    publish_failed: "Couldn't post",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function sessionLabel(status: string): string {
  const labels: Record<string, string> = {
    queued: "Starting",
    fetching: "Reading reviews",
    awaiting_scope: "Choose a range",
    generating: "Writing replies",
    ready: "Ready to review",
    publishing: "Posting replies",
    completed: "Done",
    failed: "Needs attention",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function locationLabel(status: string): string {
  const labels: Record<string, string> = {
    fetching: "Reading reviews",
    awaiting_scope: "Choose a range",
    generating: "Writing replies",
    publishing: "Posting replies",
    attention: "Needs attention",
    ready: "Replies ready",
    completed: "Done",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function statusTone(status: string): string {
  if (status === "draft_ready" || status === "published") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (status === "generating" || status === "pending") {
    return "bg-amber-100 text-amber-700";
  }
  if (status === "failed" || status === "publish_failed") {
    return "bg-rose-100 text-rose-700";
  }
  return "bg-ink/[0.06] text-ink/55";
}

function totalFor(session: ImportSession, filter: Filter): number {
  return session.locations.reduce(
    (sum, location) => sum + location.items.filter((item) => itemMatches(item, filter)).length,
    0,
  );
}

function percentFor(session: ImportSession): number {
  if (session.status === "completed") return 100;
  if (session.status === "ready" || session.status === "publishing") return 100;
  if (session.status === "generating") {
    const total = session.progress.total_drafts || 0;
    if (!total) return 0;
    return Math.min(
      100,
      Math.round(
        ((session.progress.drafts_ready + session.progress.drafts_failed) / total) * 100,
      ),
    );
  }
  const total = session.progress.total_reviews || 0;
  if (!total) return session.status === "awaiting_scope" ? 100 : 8;
  return Math.min(
    100,
    Math.round((session.progress.fetched_reviews / total) * 100),
  );
}

function ageLabel(months: number | null): string {
  if (months == null) return "Not provided by Google";
  if (months < 12) return `${months} month${months === 1 ? "" : "s"}`;
  const years = Math.floor(months / 12);
  const rest = months % 12;
  return `${years} year${years === 1 ? "" : "s"}${rest ? `, ${rest} month${rest === 1 ? "" : "s"}` : ""}`;
}

export default function ConnectImportModal({
  sessionId,
  onClose,
}: {
  sessionId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState(180);
  const [message, setMessage] = useState<string | null>(null);
  const [showSummary, setShowSummary] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);

  const query = useQuery({
    queryKey: ["connect-import", sessionId],
    queryFn: async () => (await apiFetch(`/api/v1/channels/google/import-sessions/${sessionId}`)) as ImportSession,
    refetchInterval: (queryState) => {
      const data = queryState.state.data as ImportSession | undefined;
      if (!data) return 1500;
      return ["completed", "failed", "ready"].includes(data.status) ? false : 1500;
    },
  });
  const session = query.data ?? null;

  useEffect(() => {
    if (!session) return;
    setScope(session.scope_days || 180);
  }, [session?.id, session?.scope_days]);

  useEffect(() => {
    setShowSummary(false);
  }, [session?.id]);

  useEffect(() => {
    if (!session) return;
    const available = new Set(
      session.locations.flatMap((location) =>
        location.items
          .filter((item) => item.status === "draft_ready")
          .map((item) => item.id),
      ),
    );
    setSelected((current) => {
      const next = new Set([...current].filter((id) => available.has(id)));
      return next;
    });
  }, [session]);

  const start = useMutation({
    mutationFn: async () =>
      (await apiFetch(`/api/v1/channels/google/import-sessions/${sessionId}/start`, {
        method: "POST",
        body: JSON.stringify({ scope_days: scope }),
      })) as ImportSession,
    onSuccess: (next) => {
      queryClient.setQueryData(["connect-import", sessionId], next);
      setMessage("Generating AI drafts. You can keep this open or run it in the background.");
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "Could not start draft generation.");
    },
  });

  const publish = useMutation({
    mutationFn: async (all: boolean) =>
      (await apiFetch(`/api/v1/channels/google/import-sessions/${sessionId}/publish`, {
        method: "POST",
        body: JSON.stringify({ all, item_ids: all ? [] : [...selected] }),
      })) as ImportSession,
    onSuccess: (next) => {
      queryClient.setQueryData(["connect-import", sessionId], next);
      setMessage(next.status === "completed" ? null : "Publishing replies to Google.");
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "Could not publish replies.");
    },
  });

  const generateItem = useMutation({
    mutationFn: async (itemId: string) =>
      (await apiFetch(
        `/api/v1/channels/google/import-sessions/${sessionId}/items/${itemId}/generate`,
        { method: "POST" },
      )) as ImportSession,
    onSuccess: (next) => {
      queryClient.setQueryData(["connect-import", sessionId], next);
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : "Could not generate that draft.");
    },
  });

  const draftItems = useMemo(
    () =>
      session
        ? session.locations.flatMap((location) =>
            location.items.filter((item) => item.status === "draft_ready"),
          )
        : [],
    [session],
  );
  const selectedDrafts = draftItems.filter((item) => selected.has(item.id)).length;
  const pct = session ? percentFor(session) : 0;
  const busy = start.isPending || publish.isPending || generateItem.isPending;
  const events = session?.events ?? [];
  const inProgress = session ? ACTIVE_STATUSES.includes(session.status) : true;

  function toggle(id: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAllDrafts() {
    setSelected(new Set(draftItems.map((item) => item.id)));
  }

  function finish() {
    clearActiveConnectImport();
    onClose();
  }

  // A running import must never be closed silently: ask first, and say
  // exactly what closing means — work continues, the dashboard takes over.
  function requestClose() {
    if (inProgress) setConfirmClose(true);
    else finish();
  }

  return (
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center bg-ink/40 p-0 sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="connect-import-title"
    >
      <div className="relative flex h-[94vh] w-full max-w-6xl flex-col overflow-hidden rounded-t-lg bg-white shadow-[0_18px_60px_rgba(20,16,31,0.28)] sm:h-auto sm:max-h-[90vh] sm:rounded-lg">
        <header className="shrink-0 border-b border-ink/[0.08] px-5 py-4 sm:px-7">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-deep-violet/60">
                  Google Business Profile
                </p>
                {session && (
                  <span className="rounded-sm border border-ink/[0.08] bg-ink/[0.03] px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-ink/45">
                    {sessionLabel(session.status)}
                  </span>
                )}
              </div>
              <h2 id="connect-import-title" className="mt-1 text-[20px] font-bold text-ink">
                {session?.status === "completed" ? "Your Google import is complete" : "Importing reviews and drafting replies"}
              </h2>
              <p className="mt-1 text-[12px] text-ink/50">
                {session?.status === "completed"
                  ? "A quick snapshot of what changed. The full detail lives in Analytics."
                  : "Every review is imported. AI drafts wait for your approval before anything is published."}
              </p>
            </div>
            <button
              type="button"
              onClick={requestClose}
              className="shrink-0 rounded-md border border-ink/10 bg-white px-3 py-2 text-[12px] font-bold text-ink/55 transition hover:bg-ink/[0.03] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
            >
              Close
            </button>
          </div>
          {session && session.status !== "completed" && (
            <div className="mt-4">
              <div className="flex items-center justify-between text-[11px] font-semibold text-ink/50">
                <span>
                  {session.progress.fetched_locations}/{session.progress.total_locations || "?"} locations
                  {" · "}
                  {session.progress.fetched_reviews}/{session.progress.total_reviews || "?"} reviews
                  {" · "}
                  {session.progress.drafts_ready} drafts
                </span>
                <span className="tabular-nums">{pct}%</span>
              </div>
              <div className="mt-1.5 h-1.5 overflow-hidden rounded-[2px] bg-ink/[0.08]">
                <div
                  className="h-full rounded-[2px] bg-deep-violet transition-all duration-500"
                  style={{ width: `${Math.max(2, pct)}%` }}
                />
              </div>
            </div>
          )}
          {session && session.status !== "failed" && <StageSteps status={session.status} />}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
          {message && (
            <div className="mb-4 rounded-md border border-deep-violet/15 bg-ink/[0.02] px-3 py-2.5 text-[12px] text-ink/70">
              {message}
            </div>
          )}
          {query.isError && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2.5 text-[12px] text-rose-700">
              {query.error instanceof Error ? query.error.message : "Could not load the import."}
            </div>
          )}
          {!session && query.isPending && (
            <div className="py-16 text-center text-[13px] text-ink/50">Loading import…</div>
          )}

          {session && inProgress ? (
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">
              <div className="min-w-0">
                {["queued", "fetching"].includes(session.status) && <FetchStage session={session} />}

                {session.status === "awaiting_scope" && (
                  <ScopeStage
                    session={session}
                    scope={scope}
                    setScope={setScope}
                    busy={busy}
                    onStart={() => start.mutate()}
                  />
                )}

                {["generating", "ready", "publishing"].includes(session.status) && (
                  <WorkspaceStage
                    session={session}
                    filter={filter}
                    setFilter={setFilter}
                    selected={selected}
                    toggle={toggle}
                    selectAllDrafts={selectAllDrafts}
                    busy={busy}
                    onGenerate={(id) => generateItem.mutate(id)}
                  />
                )}
              </div>
              <ProgressFeed events={events} status={session.status} />
            </div>
          ) : null}

          {session?.status === "completed" && session.summary ? (
            showSummary ? (
              <SummaryStage session={session} onClose={finish} />
            ) : (
              <CompletionStage
                session={session}
                onViewSummary={() => setShowSummary(true)}
                onClose={finish}
              />
            )
          ) : null}

          {session?.status === "completed" && !session.summary ? (
            <div className="rounded-md border border-ink/[0.08] bg-ink/[0.025] p-5 text-[13px] text-ink/60">
              <p className="font-bold text-ink">Your Google import is complete</p>
              <p className="mt-1">
                {session.progress.fetched_reviews || 0} reviews fetched ·{" "}
                {session.progress.drafts_ready || 0} drafts ready for approval ·{" "}
                {session.progress.drafts_failed || 0} failed.
              </p>
              <p className="mt-1 text-[12px] text-ink/45">
                New reviews keep flowing in automatically. Drafts appear in Reviews and Outbox.
              </p>
            </div>
          ) : null}

          {session?.status === "failed" && (
            <div className="rounded-md border border-rose-200 bg-rose-50 p-5 text-[13px] text-rose-800">
              <p className="font-bold">The import stopped.</p>
              <p className="mt-1">{session.error || "Google or the AI provider returned an error."}</p>
              <p className="mt-2 text-[12px] text-rose-700/80">
                The session is saved. Reconnecting is not required; retry from Channels after checking the provider key.
              </p>
            </div>
          )}
        </div>

        {session && session.status !== "completed" && (
          <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-ink/[0.08] bg-white px-5 py-4 sm:px-7">
            {session.status !== "failed" && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-ink/10 bg-white px-4 py-2.5 text-[12px] font-bold text-ink/65 transition active:translate-y-[2px] active:scale-[0.98]"
              >
                Run in background
              </button>
            )}
            {session.status === "failed" ? (
              <span className="text-[12px] text-rose-700">
                Close this panel and reconnect Google to retry the import.
              </span>
            ) : session.status === "ready" ? (
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => publish.mutate(false)}
                  disabled={!selectedDrafts || busy}
                  className="rounded-md bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {publish.isPending ? "Publishing…" : `Publish selected (${selectedDrafts})`}
                </button>
                <button
                  type="button"
                  onClick={() => publish.mutate(true)}
                  disabled={!draftItems.length || busy}
                  className="rounded-md border border-deep-violet/25 bg-white px-4 py-2.5 text-[12px] font-bold text-deep-violet transition active:translate-y-[2px] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Publish all drafts
                </button>
              </div>
            ) : session.status === "publishing" ? (
              <span className="text-[12px] font-bold text-deep-violet">Publishing to Google…</span>
            ) : (
              <span className="text-[12px] text-ink/45">
                {session.status === "awaiting_scope"
                  ? "Choose a range above to start generating drafts."
                  : "Progress continues even if you close this window."}
              </span>
            )}
          </footer>
        )}

        {confirmClose && (
          <div
            className="absolute inset-0 z-10 flex items-center justify-center bg-ink/45 p-4"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-close-title"
          >
            <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-[0_18px_60px_rgba(20,16,31,0.28)]">
              <p id="confirm-close-title" className="text-[15px] font-bold text-ink">
                Close this panel?
              </p>
              <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink/60">
                The import keeps running in the background. You can review drafts and publish
                replies from the dashboard at any time.
              </p>
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setConfirmClose(false)}
                  className="rounded-md border border-ink/10 bg-white px-4 py-2.5 text-[12px] font-bold text-ink/65 transition active:translate-y-[2px] active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
                >
                  Keep this open
                </button>
                <button
                  type="button"
                  onClick={finish}
                  className="rounded-md bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
                >
                  Close panel
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ProgressFeed({ events, status }: { events: ImportEvent[]; status: string }) {
  const boxRef = useRef<HTMLDivElement | null>(null);
  const active = ["queued", "fetching", "awaiting_scope", "generating", "publishing"].includes(status);

  useEffect(() => {
    const box = boxRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [events.length]);

  return (
    <aside
      aria-live="polite"
      className="order-first overflow-hidden rounded-md border border-ink/[0.08] bg-ink/[0.025] lg:order-none"
    >
      <div className="flex items-center gap-2 border-b border-ink/[0.08] px-3 py-2">
        <span
          className={`h-1.5 w-1.5 rounded-full ${active ? "bg-emerald-500" : "bg-ink/20"}`}
          aria-hidden
        />
        <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-ink/45">Progress</p>
      </div>
      <div ref={boxRef} className="max-h-[190px] overflow-y-auto px-3 py-2.5 lg:max-h-[420px]">
        {events.length === 0 ? (
          <p className="py-3 text-[11.5px] text-ink/40">
            {status === "queued" ? "Getting things ready…" : "Waiting for the first update…"}
          </p>
        ) : (
          <ol className="space-y-2">
            {events.map((event) => (
              <li key={event.id} className="flex gap-2 text-[11.5px] leading-snug">
                <span
                  className={`mt-[6px] h-1 w-1 shrink-0 rounded-full ${eventDot(event.level)}`}
                  aria-hidden
                />
                <span className={eventTone(event.level)}>{event.message}</span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </aside>
  );
}

function eventDot(level: string): string {
  if (level === "success") return "bg-emerald-500/60";
  if (level === "warning") return "bg-amber-500/70";
  if (level === "error") return "bg-rose-500/70";
  return "bg-ink/25";
}

function eventTone(level: string): string {
  if (level === "warning") return "text-amber-700";
  if (level === "error") return "text-rose-700";
  return "text-ink/60";
}

function FetchStage({ session }: { session: ImportSession }) {
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-ink/[0.08] bg-white p-5">
        <p className="text-[13px] font-bold text-ink">Fetching every review from Google</p>
        <p className="mt-1 text-[12px] leading-relaxed text-ink/55">
          We are reading every location and review first. AI drafts start only after you choose a range.
        </p>
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <Metric
            label="Locations"
            value={`${session.progress.fetched_locations}/${session.progress.total_locations || "?"}`}
          />
          <Metric label="Reviews found" value={String(session.progress.fetched_reviews)} />
          <Metric label="Status" value="Reading Google" />
        </div>
      </div>
      {session.locations.length === 0 ? (
        <p className="rounded-md border border-ink/[0.08] bg-white px-4 py-3 text-[12px] text-ink/45">
          Waiting for the first location to return…
        </p>
      ) : (
        session.locations.map((location) => (
          <div key={location.channel_id} className="rounded-md border border-ink/[0.08] bg-white p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[13px] font-bold text-ink">{location.name}</p>
                <p className="text-[11px] text-ink/40">{location.address || "Google location"}</p>
              </div>
              <span className="text-[11px] font-semibold text-ink/45">
                {location.items.length} reviews
              </span>
            </div>
          </div>
        ))
      )}
    </div>
  );
}

function ScopeStage({
  session,
  scope,
  setScope,
  busy,
  onStart,
}: {
  session: ImportSession;
  scope: number;
  setScope: (days: number) => void;
  busy: boolean;
  onStart: () => void;
}) {
  const longRange = scope === 365 || scope === 0;
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-ink/[0.08] bg-white p-5">
        <p className="text-[13px] font-bold text-ink">
          {session.progress.fetched_reviews} reviews imported across {session.progress.fetched_locations} locations
        </p>
        <p className="mt-1 text-[12px] leading-relaxed text-ink/55">
          Choose how far back the AI should automatically generate drafts. Every review is still listed
          and can be handled individually.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {SCOPES.map((option) => (
          <button
            key={option.days}
            type="button"
            onClick={() => setScope(option.days)}
            className={`rounded-md border p-4 text-left transition ${
              scope === option.days
                ? "border-deep-violet bg-deep-violet/[0.05]"
                : "border-ink/[0.08] bg-white hover:border-deep-violet/25"
            }`}
          >
            <span className="text-[13px] font-bold text-ink">{option.label}</span>
            <span className="mt-1 block text-[11px] text-ink/45">
              {option.days === 0
                ? "Every unanswered review in the history."
                : `Reviews updated in the last ${option.days === 180 ? "6 months" : option.days === 365 ? "12 months" : "30 days"}.`}
            </span>
          </button>
        ))}
      </div>
      {longRange && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-[12px] leading-relaxed text-amber-800">
          A longer range means more AI calls and a slower first import. Drafts are still never
          published automatically.
        </div>
      )}
      <button
        type="button"
        onClick={onStart}
        disabled={busy}
        className="rounded-md bg-deep-violet px-5 py-3 text-[13px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] disabled:opacity-40"
      >
        {busy ? "Starting…" : "Generate drafts"}
      </button>
    </div>
  );
}

function WorkspaceStage({
  session,
  filter,
  setFilter,
  selected,
  toggle,
  selectAllDrafts,
  busy,
  onGenerate,
}: {
  session: ImportSession;
  filter: Filter;
  setFilter: (filter: Filter) => void;
  selected: Set<string>;
  toggle: (id: string) => void;
  selectAllDrafts: () => void;
  busy: boolean;
  onGenerate: (id: string) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        {FILTERS.map((option) => {
          const count = totalFor(session, option.id);
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => setFilter(option.id)}
              className={`rounded border px-2.5 py-1.5 text-[11px] font-bold transition ${
                filter === option.id
                  ? "border-deep-violet bg-deep-violet text-white"
                  : "border-ink/[0.08] bg-white text-ink/55 hover:border-ink/20 hover:text-ink/70"
              }`}
            >
              {option.label} <span className="tabular-nums opacity-60">{count}</span>
            </button>
          );
        })}
        {totalFor(session, "draft_ready") > 0 && (
          <button
            type="button"
            onClick={selectAllDrafts}
            className="ml-auto text-[11px] font-bold text-deep-violet underline underline-offset-2"
          >
            Select all drafts
          </button>
        )}
      </div>
      {session.error && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-[12px] text-amber-800">
          {session.error}
        </div>
      )}
      {session.locations.map((location) => {
        const visible = location.items.filter((item) => itemMatches(item, filter));
        if (!visible.length) return null;
        return (
          <section key={location.channel_id} className="overflow-hidden rounded-md border border-ink/[0.08] bg-white">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink/[0.08] px-4 py-3">
              <div>
                <p className="text-[13px] font-bold text-ink">{location.name}</p>
                <p className="text-[11px] text-ink/40">{location.address || "Google location"}</p>
              </div>
              <span className="rounded-sm border border-ink/[0.08] bg-ink/[0.03] px-2 py-0.5 text-[10px] font-bold capitalize text-ink/50">
                {locationLabel(location.status)}
              </span>
            </div>
            {location.items.length > 0 && (
              <div className="px-4 pt-2.5">
                <div className="h-1 overflow-hidden rounded-[2px] bg-ink/[0.06]">
                  <div
                    className="h-full rounded-[2px] bg-deep-violet/70 transition-all duration-500"
                    style={{
                      width: `${Math.round(
                        (location.items.filter((item) =>
                          ["draft_ready", "already_replied", "outside_scope", "published"].includes(item.status),
                        ).length /
                          location.items.length) *
                          100,
                      )}%`,
                    }}
                  />
                </div>
              </div>
            )}
            <div className="divide-y divide-ink/[0.06]">
              {visible.map((item) => (
                <ReviewRow
                  key={item.id}
                  item={item}
                  checked={selected.has(item.id)}
                  onToggle={() => toggle(item.id)}
                  busy={busy}
                  onGenerate={() => onGenerate(item.id)}
                />
              ))}
            </div>
          </section>
        );
      })}
      {session.locations.every((location) => !location.items.some((item) => itemMatches(item, filter))) && (
        <p className="rounded-md border border-ink/[0.08] bg-white px-4 py-8 text-center text-[12px] text-ink/45">
          No reviews match this filter.
        </p>
      )}
    </div>
  );
}

function ReviewRow({
  item,
  checked,
  onToggle,
  busy,
  onGenerate,
}: {
  item: ImportItem;
  checked: boolean;
  onToggle: () => void;
  busy: boolean;
  onGenerate: () => void;
}) {
  return (
    <div className="flex gap-3 px-4 py-3">
      <input
        type="checkbox"
        checked={checked}
        disabled={busy || item.status !== "draft_ready"}
        onChange={onToggle}
        aria-label={`Select review from ${item.reviewer_name || "customer"}`}
        className="mt-1 h-4 w-4 shrink-0 rounded-[3px] border-ink/20 text-deep-violet focus:ring-deep-violet disabled:opacity-30"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] font-bold text-ink">{item.reviewer_name || "Google reviewer"}</span>
          <span className="text-[11px] font-bold text-amber-500">
            {"★".repeat(Math.max(0, Math.min(5, item.rating)))}
            <span className="text-ink/15">{"★".repeat(Math.max(0, 5 - item.rating))}</span>
          </span>
          <span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-bold ${statusTone(item.status)}`}>
            {statusLabel(item.status)}
          </span>
          {item.review_time && (
            <span className="text-[10px] text-ink/35">
              {new Date(item.review_time).toLocaleDateString()}
            </span>
          )}
        </div>
        {item.review_text && (
          <p className="mt-1 line-clamp-3 text-[12px] leading-relaxed text-ink/65">{item.review_text}</p>
        )}
        {item.draft_text && (
          <div className="mt-2 rounded border-l-2 border-deep-violet/30 bg-ink/[0.025] px-3 py-2">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-deep-violet/55">
              {item.status === "already_replied"
                ? "Existing reply"
                : item.status === "published"
                  ? "Published reply"
                  : "AI draft"}
            </p>
            <p className="mt-1 line-clamp-4 text-[12px] leading-relaxed text-ink/70">{item.draft_text}</p>
          </div>
        )}
        {item.error && <p className="mt-1 text-[11px] text-rose-600">{item.error}</p>}
        {["outside_scope", "failed"].includes(item.status) && (
          <button
            type="button"
            onClick={onGenerate}
            disabled={busy}
            className="mt-2 rounded border border-deep-violet/25 bg-white px-3 py-1.5 text-[10px] font-bold text-deep-violet transition active:translate-y-[1px] active:scale-[0.98] disabled:opacity-40"
          >
            Generate draft
          </button>
        )}
      </div>
    </div>
  );
}

function CompletionStage({
  session,
  onViewSummary,
  onClose,
}: {
  session: ImportSession;
  onViewSummary: () => void;
  onClose: () => void;
}) {
  const summary = session.summary!;
  const nothingToReply = summary.unanswered_before === 0;
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-ink/[0.08] bg-white p-5">
        <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-deep-violet/60">
          Import complete
        </p>
        <h3 className="mt-1 text-[18px] font-bold text-ink">
          {nothingToReply ? "Nothing needed a reply" : "Your replies are in"}
        </h3>
        <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed text-ink/60">
          {nothingToReply
            ? `We found ${summary.reviews_total} reviews across ${session.progress.fetched_locations} locations. Every one already has a reply on Google, so no AI reply was generated.`
            : `We found ${summary.reviews_total} reviews. ${summary.already_answered} already had replies and ${summary.published_now} new replies were published.`}
        </p>
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <Metric label="Reviews found" value={String(summary.reviews_total)} />
          <Metric label="Already answered" value={String(summary.already_answered)} />
          <Metric
            label={nothingToReply ? "Drafts created" : "Published now"}
            value={String(nothingToReply ? 0 : summary.published_now)}
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onViewSummary}
          className="rounded-md bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98]"
        >
          View summary &amp; analytics
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-ink/10 bg-white px-4 py-2.5 text-[12px] font-bold text-ink/65 transition active:translate-y-[2px] active:scale-[0.98]"
        >
          Close
        </button>
      </div>
      <p className="text-[11px] leading-relaxed text-ink/40">
        The import also analyzes reviews to build your insights. That analysis is metered even when no
        reply is needed; the exact calls are listed under Billing → Credit ledger.
      </p>
    </div>
  );
}

function SummaryStage({ session, onClose }: { session: ImportSession; onClose: () => void }) {
  const summary = session.summary!;
  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-4">
        <Metric label="Unanswered before" value={String(summary.unanswered_before)} />
        <Metric label="Published now" value={String(summary.published_now)} />
        <Metric label="Already answered" value={String(summary.already_answered)} />
        <Metric label="Needs attention" value={String(summary.failed)} />
      </div>
      <div className="rounded-md border border-ink/[0.08] bg-white p-5">
        <p className="text-[13px] font-bold text-ink">This business on Google</p>
        <p className="mt-1 text-[12px] text-ink/55">
          Oldest connected location:{" "}
          <strong className="text-ink/75">{ageLabel(summary.business_age_months)}</strong>.{" "}
          {summary.reviews_total} reviews were imported in this pass.
        </p>
      </div>
      <div className="grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-ink/[0.08] bg-white p-4">
          <p className="text-[12px] font-bold text-ink">Reviews received, last 12 months</p>
          <VolumeBars data={summary.review_volume} />
        </div>
        <div className="rounded-md border border-ink/[0.08] bg-white p-4">
          <p className="text-[12px] font-bold text-ink">Rating over time</p>
          <RatingScatter data={summary.rating_scatter} />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <a
          href={summary.analytics_url || "/dashboard/analytics"}
          className="rounded-md bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98]"
        >
          View full analytics
        </a>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-ink/10 bg-white px-4 py-2.5 text-[12px] font-bold text-ink/65 transition active:translate-y-[2px] active:scale-[0.98]"
        >
          Done
        </button>
      </div>
      <p className="text-[11px] leading-relaxed text-ink/40">
        This panel disappears after you close it. The reviews, drafts and published replies remain
        available in Reviews, Outbox and Analytics.
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-ink/[0.08] bg-white p-3">
      <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/35">{label}</p>
      <p className="mt-1.5 text-[16px] font-bold tabular-nums text-ink">{value}</p>
    </div>
  );
}

function VolumeBars({ data }: { data: { month: string; count: number }[] }) {
  if (!data.length) return <p className="mt-3 text-[11px] text-ink/40">No review volume yet.</p>;
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div className="mt-3 flex h-24 items-end gap-1.5">
      {data.map((d) => (
        <div key={d.month} className="flex min-w-0 flex-1 flex-col items-center justify-end gap-1">
          <div
            className="w-full rounded-t-[2px] bg-deep-violet/70"
            style={{ height: `${Math.max(4, (d.count / max) * 76)}px` }}
            title={`${d.month}: ${d.count}`}
          />
          <span className="max-w-full truncate text-[8px] text-ink/35">{d.month.slice(5)}</span>
        </div>
      ))}
    </div>
  );
}

function RatingScatter({ data }: { data: { date: string; rating: number }[] }) {
  if (!data.length) return <p className="mt-3 text-[11px] text-ink/40">No rating history yet.</p>;
  const points = data.slice(0, 80);
  return (
    <svg viewBox="0 0 300 110" className="mt-2 h-28 w-full" role="img" aria-label="Rating over time">
      {[1, 2, 3, 4, 5].map((rating) => (
        <line
          key={rating}
          x1="6"
          x2="294"
          y1={96 - (rating - 1) * 20}
          y2={96 - (rating - 1) * 20}
          stroke="rgba(20,16,31,0.06)"
          strokeWidth="1"
        />
      ))}
      {points.map((point, index) => {
        const x = 8 + (index / Math.max(1, points.length - 1)) * 284;
        const y = 96 - (Math.max(1, Math.min(5, point.rating)) - 1) * 20;
        return <circle key={`${point.date}-${index}`} cx={x} cy={y} r="2.6" fill="#3D1D6E" opacity="0.7" />;
      })}
    </svg>
  );
}
