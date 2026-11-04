"use client";

import { useEffect, useMemo, useState } from "react";
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
    pending: "Waiting",
    generating: "Generating",
    draft_ready: "Draft ready",
    already_replied: "Already replied",
    outside_scope: "Outside selected range",
    failed: "Generation failed",
    published: "Published",
    publish_failed: "Publish failed",
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

  return (
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center bg-ink/40 p-0 sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="connect-import-title"
    >
      <div className="flex h-[94vh] w-full max-w-5xl flex-col overflow-hidden rounded-t-[32px] bg-white shadow-[0_24px_80px_rgba(20,16,31,0.30)] sm:h-auto sm:max-h-[90vh] sm:rounded-[32px]">
        <header className="shrink-0 border-b border-ink/[0.06] px-5 py-4 sm:px-7">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.16em] text-deep-violet/60">
                Google Business Profile
              </p>
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
              onClick={onClose}
              className="rounded-[20px] border border-ink/10 bg-white px-3 py-2 text-[12px] font-bold text-ink/55 transition hover:bg-ink/[0.03] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
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
                <span>{pct}%</span>
              </div>
              <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-ink/[0.06]">
                <div
                  className="h-full rounded-full bg-deep-violet transition-all duration-500"
                  style={{ width: `${Math.max(4, pct)}%` }}
                />
              </div>
            </div>
          )}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4 sm:px-7">
          {message && (
            <div className="mb-4 rounded-[20px] border border-deep-violet/15 bg-white px-4 py-3 text-[12px] text-ink/70">
              {message}
            </div>
          )}
          {query.isError && (
            <div className="rounded-[20px] bg-rose-50 px-4 py-3 text-[12px] text-rose-700">
              {query.error instanceof Error ? query.error.message : "Could not load the import."}
            </div>
          )}
          {!session && query.isPending && (
            <div className="py-16 text-center text-[13px] text-ink/50">Loading import…</div>
          )}

          {session?.status === "queued" || session?.status === "fetching" ? (
            <FetchStage session={session} />
          ) : null}

          {session?.status === "awaiting_scope" ? (
            <ScopeStage
              session={session}
              scope={scope}
              setScope={setScope}
              busy={busy}
              onStart={() => start.mutate()}
            />
          ) : null}

          {session && ["generating", "ready", "publishing"].includes(session.status) ? (
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
          ) : null}

          {session?.status === "completed" && session.summary ? (
            <SummaryStage session={session} onClose={finish} />
          ) : null}

          {session?.status === "completed" && !session.summary ? (
            <div className="rounded-[24px] bg-ink/[0.025] p-5 text-[13px] text-ink/60">
              The import completed. Reviews and drafts are available in Reviews and Outbox.
            </div>
          ) : null}

          {session?.status === "failed" && (
            <div className="rounded-[24px] bg-rose-50 p-5 text-[13px] text-rose-800">
              <p className="font-bold">The import stopped.</p>
              <p className="mt-1">{session.error || "Google or the AI provider returned an error."}</p>
              <p className="mt-2 text-[12px] text-rose-700/80">
                The session is saved. Reconnecting is not required; retry from Channels after checking the provider key.
              </p>
            </div>
          )}
        </div>

        {session && session.status !== "completed" && (
          <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-ink/[0.06] bg-white px-5 py-4 sm:px-7">
            {session.status !== "failed" && (
              <button
                type="button"
                onClick={onClose}
                className="rounded-[24px] border border-ink/10 bg-white px-4 py-2.5 text-[12px] font-bold text-ink/65 transition active:translate-y-[2px] active:scale-[0.98]"
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
                  className="rounded-[24px] bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {publish.isPending ? "Publishing…" : `Publish selected (${selectedDrafts})`}
                </button>
                <button
                  type="button"
                  onClick={() => publish.mutate(true)}
                  disabled={!draftItems.length || busy}
                  className="rounded-[24px] border border-deep-violet/20 bg-white px-4 py-2.5 text-[12px] font-bold text-deep-violet transition active:translate-y-[2px] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
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
      </div>
    </div>
  );
}

function FetchStage({ session }: { session: ImportSession }) {
  return (
    <div className="space-y-4">
      <div className="rounded-[24px] bg-ink/[0.025] p-5">
        <p className="text-[13px] font-bold text-ink">Fetching every review from Google</p>
        <p className="mt-1 text-[12px] leading-relaxed text-ink/55">
          We are reading every location and review first. AI drafts start only after you choose a range.
        </p>
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          <Metric label="Locations" value={`${session.progress.fetched_locations}/${session.progress.total_locations || "?"}`} />
          <Metric label="Reviews found" value={String(session.progress.fetched_reviews)} />
          <Metric label="Status" value="Reading Google" />
        </div>
      </div>
      {session.locations.length === 0 ? (
        <p className="rounded-[20px] bg-white px-4 py-3 text-[12px] text-ink/45">
          Waiting for the first location to return…
        </p>
      ) : (
        session.locations.map((location) => (
          <div key={location.channel_id} className="rounded-[20px] border border-ink/[0.06] bg-white p-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-[13px] font-bold text-ink">{location.name}</p>
                <p className="text-[11px] text-ink/40">{location.address || "Google location"}</p>
              </div>
              <span className="text-[11px] font-semibold text-ink/45">{location.items.length} reviews</span>
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
    <div className="space-y-5">
      <div className="rounded-[24px] bg-ink/[0.025] p-5">
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
            className={`rounded-[24px] border p-4 text-left transition ${
              scope === option.days
                ? "border-deep-violet bg-deep-violet/[0.05]"
                : "border-black/[0.06] bg-white hover:border-deep-violet/25"
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
        <div className="rounded-[20px] bg-amber-50 px-4 py-3 text-[12px] leading-relaxed text-amber-800">
          A longer range means more AI calls and a slower first import. Drafts are still never
          published automatically.
        </div>
      )}
      <button
        type="button"
        onClick={onStart}
        disabled={busy}
        className="rounded-[24px] bg-deep-violet px-5 py-3 text-[13px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] disabled:opacity-40"
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
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((option) => {
          const count = totalFor(session, option.id);
          return (
            <button
              key={option.id}
              type="button"
              onClick={() => setFilter(option.id)}
              className={`rounded-full px-3 py-1.5 text-[11px] font-bold transition ${
                filter === option.id
                  ? "bg-deep-violet text-white"
                  : "bg-ink/[0.05] text-ink/55 hover:bg-ink/[0.08]"
              }`}
            >
              {option.label} <span className="opacity-60">{count}</span>
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
        <div className="rounded-[20px] bg-amber-50 px-4 py-3 text-[12px] text-amber-800">
          {session.error}
        </div>
      )}
      {session.locations.map((location) => {
        const visible = location.items.filter((item) => itemMatches(item, filter));
        if (!visible.length) return null;
        return (
          <section key={location.channel_id} className="rounded-[24px] border border-ink/[0.06] bg-white">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink/[0.06] px-4 py-3">
              <div>
                <p className="text-[13px] font-bold text-ink">{location.name}</p>
                <p className="text-[11px] text-ink/40">{location.address || "Google location"}</p>
              </div>
              <span className="rounded-full bg-ink/[0.05] px-2.5 py-1 text-[10px] font-bold capitalize text-ink/50">
                {location.status.replaceAll("_", " ")}
              </span>
            </div>
            {location.items.length > 0 && (
              <div className="px-4 pt-2">
                <div className="h-1 overflow-hidden rounded-full bg-ink/[0.06]">
                  <div
                    className="h-full rounded-full bg-deep-violet/70 transition-all duration-500"
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
            <div className="divide-y divide-ink/[0.05]">
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
        <p className="rounded-[20px] bg-white px-4 py-8 text-center text-[12px] text-ink/45">
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
        className="mt-1 h-4 w-4 shrink-0 rounded border-ink/20 text-deep-violet focus:ring-deep-violet disabled:opacity-30"
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[12px] font-bold text-ink">{item.reviewer_name || "Google reviewer"}</span>
          <span className="text-[11px] font-bold text-amber-500">
            {"★".repeat(Math.max(0, Math.min(5, item.rating)))}
            <span className="text-ink/15">{"★".repeat(Math.max(0, 5 - item.rating))}</span>
          </span>
          <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${statusTone(item.status)}`}>
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
          <div className="mt-2 rounded-[16px] bg-deep-violet/[0.045] px-3 py-2">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-deep-violet/55">
              AI draft
            </p>
            <p className="mt-1 line-clamp-4 text-[12px] leading-relaxed text-ink/70">{item.draft_text}</p>
          </div>
        )}
        {item.error && (
          <p className="mt-1 text-[11px] text-rose-600">{item.error}</p>
        )}
        {["outside_scope", "failed"].includes(item.status) && (
          <button
            type="button"
            onClick={onGenerate}
            disabled={busy}
            className="mt-2 rounded-full border border-deep-violet/20 bg-white px-3 py-1.5 text-[10px] font-bold text-deep-violet transition active:translate-y-[1px] active:scale-[0.98] disabled:opacity-40"
          >
            Generate draft
          </button>
        )}
      </div>
    </div>
  );
}

function SummaryStage({ session, onClose }: { session: ImportSession; onClose: () => void }) {
  const summary = session.summary!;
  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-4">
        <Metric label="Unanswered before" value={String(summary.unanswered_before)} />
        <Metric label="Published now" value={String(summary.published_now)} />
        <Metric label="Already answered" value={String(summary.already_answered)} />
        <Metric label="Needs attention" value={String(summary.failed)} />
      </div>
      <div className="rounded-[24px] bg-ink/[0.025] p-5">
        <p className="text-[13px] font-bold text-ink">This business on Google</p>
        <p className="mt-1 text-[12px] text-ink/55">
          Oldest connected location: <strong className="text-ink/75">{ageLabel(summary.business_age_months)}</strong>.
          {" "}
          {summary.reviews_total} reviews were imported in this pass.
        </p>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-[24px] border border-ink/[0.06] bg-white p-4">
          <p className="text-[12px] font-bold text-ink">Reviews received, last 12 months</p>
          <VolumeBars data={summary.review_volume} />
        </div>
        <div className="rounded-[24px] border border-ink/[0.06] bg-white p-4">
          <p className="text-[12px] font-bold text-ink">Rating over time</p>
          <RatingScatter data={summary.rating_scatter} />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <a
          href={summary.analytics_url || "/dashboard/analytics"}
          className="rounded-[24px] bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98]"
        >
          View full analytics
        </a>
        <button
          type="button"
          onClick={onClose}
          className="rounded-[24px] border border-ink/10 bg-white px-4 py-2.5 text-[12px] font-bold text-ink/65 transition active:translate-y-[2px] active:scale-[0.98]"
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
    <div className="rounded-[20px] bg-white p-3 shadow-[0_1px_0_rgba(255,255,255,0.8)_inset,0_4px_12px_rgba(20,16,31,0.04)]">
      <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/35">{label}</p>
      <p className="mt-1.5 text-[16px] font-bold text-ink">{value}</p>
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
            className="w-full rounded-t-[4px] bg-deep-violet/70"
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
