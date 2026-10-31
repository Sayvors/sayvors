"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/lib/query-keys";
import PlatformMark, { platformLabel } from "@/components/channels/PlatformMark";
import { fetchLeads, updateLead, type Lead, type LeadStage } from "@/lib/api-leads";
import {
  LEAD_CATEGORIES,
  LEAD_CATEGORY_LABELS,
  leadCategoryLabel,
  type LeadCategory,
} from "@/lib/lead-labels";

/*
 * The all-channels leads board: every conversation the messaging engine
 * turned into a lead — WhatsApp, Instagram, Messenger — in one grid.
 *
 * Reads the stored /api/v1/leads rows; capture and follow-up scheduling
 * happen in the pipeline, this board only renders, filters, and moves a
 * lead through new -> qualified -> follow_up -> converted/lost. Filters
 * are client-side (one fetch, <=200 rows): status chips, channel chips
 * (all-channels mode only), and an age select. With `platform` set the
 * fetch is server-filtered and the channel row hides (the IG hub tab).
 *
 * Cards, not rows: who the lead is (avatar, handle), what they want
 * (intent + running summary), their requirements as a checklist (the bot
 * asks for them comma-separated, so the stored request splits back
 * apart), and their contact facts with provenance. Every card deep-links
 * to its unified-inbox thread.
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";
const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

const STAGE_CHIP: Record<LeadStage, string> = {
  new: "bg-[var(--ui-ink)] text-[var(--ui-on-ink)]",
  qualified: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]",
  follow_up: "border border-[var(--ui-line)] text-[var(--ui-ink)]",
  converted: "bg-[var(--ui-sunken)] text-[var(--ui-ink)]",
  lost: "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)]",
};

const STAGE_LABEL: Record<LeadStage, string> = {
  new: "New",
  qualified: "Qualified",
  follow_up: "Follow-up",
  converted: "Converted",
  lost: "Lost",
};

const STAGES: LeadStage[] = ["new", "qualified", "follow_up", "converted", "lost"];

const CHANNELS = ["whatsapp", "instagram", "facebook"] as const;

const AGES = [
  { key: "any", label: "Any time", days: null },
  { key: "24h", label: "Last 24 hours", days: 1 },
  { key: "7d", label: "Last 7 days", days: 7 },
  { key: "30d", label: "Last 30 days", days: 30 },
] as const;
type AgeKey = (typeof AGES)[number]["key"];

/*
 * The bot asks customers to list requirements comma-separated (the prompt
 * enforces it), so the stored request splits back into a clean checklist.
 * Latin + Arabic commas and semicolons; deduped; capped so one rambling
 * sentence can't stretch a card.
 */
function requirements(request: string | null): string[] {
  if (!request) return [];
  return [
    ...new Set(request.split(/[,،;]/).map((s) => s.trim()).filter(Boolean)),
  ].slice(0, 8);
}

function nudgeIn(iso: string): string {
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  if (mins <= 0) return "nudge due";
  if (mins < 60) return `nudge in ${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `nudge in ${hours}h`;
  return `nudge in ${Math.round(hours / 24)}d`;
}

function timeAgo(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins || 1}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function Avatar({ lead }: { lead: Lead }) {
  if (lead.avatar_url) {
    return (
      <Image
        src={lead.avatar_url}
        alt=""
        width={44}
        height={44}
        className="h-11 w-11 shrink-0 rounded-full border border-[var(--ui-line)] object-cover"
        unoptimized
      />
    );
  }
  const initial = (lead.contact_name || "").trim().charAt(0).toUpperCase();
  if (initial) {
    return (
      <span
        aria-hidden
        className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)] text-[15px] font-bold ${INK}`}
      >
        {initial}
      </span>
    );
  }
  return (
    <span
      aria-hidden
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)]"
    >
      <PlatformMark platform={lead.platform} size={18} />
    </span>
  );
}

function LeadCard({
  lead,
  busy,
  onMove,
  onCategory,
}: {
  lead: Lead;
  busy: boolean;
  onMove: (lead: Lead, stage: LeadStage) => void;
  onCategory: (lead: Lead, category: LeadCategory) => void;
}) {
  const reqs = requirements(lead.request);
  const categoryLabel = leadCategoryLabel(lead.category);
  return (
    <li
      className={`flex flex-col rounded-[12px] border p-4 ${
        lead.priority === "important"
          ? "border-red-500 bg-red-50"
          : "border-[var(--ui-line)] bg-[var(--ui-surface)]"
      }`}
    >
      <div className="flex items-start gap-3">
        <Avatar lead={lead} />
        <div className="min-w-0 flex-1">
          <p className={`truncate text-[14px] font-semibold ${INK}`}>
            {lead.contact_name ||
              (lead.contact_username ? `@${lead.contact_username}` : `${platformLabel(lead.platform)} user`)}
          </p>
          <p className={`mt-0.5 flex items-center gap-1.5 text-[11px] ${INK2}`}>
            <PlatformMark platform={lead.platform} size={11} />
            <time
              dateTime={lead.created_at}
              title={new Date(lead.created_at).toLocaleString()}
              className="tabular-nums"
            >
              {timeAgo(lead.created_at)}
            </time>
            {lead.contact_username && <span>· @{lead.contact_username}</span>}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          {lead.priority === "important" && (
            <span
              title={
                lead.priority_since
                  ? `Escalated ${timeAgo(lead.priority_since)} — the AI could not resolve this thread`
                  : "Escalated — the AI could not resolve this thread"
              }
              className="rounded-[8px] bg-coral/10 px-2 py-0.5 text-[11px] font-bold text-coral"
            >
              Important
            </span>
          )}
          <span
            className={`rounded-[8px] px-2 py-0.5 text-[11px] font-bold ${STAGE_CHIP[lead.stage]}`}
          >
            {STAGE_LABEL[lead.stage]}
          </span>
          {lead.opt_out && (
            <span className="rounded-[8px] border border-[var(--ui-line)] px-2 py-0.5 text-[10px] font-semibold text-[var(--ui-ink-2)]">
              Opted out
            </span>
          )}
        </div>
      </div>

      <div className="mt-3 flex items-start gap-2">
        {categoryLabel && (
          <span className="shrink-0 rounded-[8px] border border-[var(--ui-line)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink)]">
            {categoryLabel}
          </span>
        )}
        <p className={`min-w-0 flex-1 text-[13px] leading-snug ${INK}`}>
          {lead.summary || "No summary captured yet."}
        </p>
      </div>

      {reqs.length > 0 && (
        <div className="mt-3 rounded-[8px] bg-[var(--ui-sunken)] p-3">
          <p className={`text-[10px] font-bold uppercase tracking-wide ${INK2}`}>Requirements</p>
          <ul className="mt-1.5 space-y-1">
            {reqs.map((r) => (
              <li key={r} className={`flex gap-1.5 text-[12px] leading-snug ${INK}`}>
                <span aria-hidden className={INK2}>
                  —
                </span>
                <span className="min-w-0">{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {(lead.phone_number || lead.next_action_at) && (
        <div className={`mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] ${INK2}`}>
          {lead.phone_number && (
            <span className="flex items-center gap-1.5">
              <span className={`font-semibold tabular-nums ${INK}`}>{lead.phone_number}</span>
              <span className="rounded-[6px] border border-[var(--ui-line)] px-1.5 py-px text-[10px] font-semibold">
                {lead.phone_status === "verified" ? "Verified · WhatsApp" : "Stated"}
              </span>
            </span>
          )}
          {lead.stage === "follow_up" && lead.next_action_at && (
            <span
              title={new Date(lead.next_action_at).toLocaleString()}
              className="tabular-nums"
            >
              {nudgeIn(lead.next_action_at)}
            </span>
          )}
        </div>
      )}

      <div className="mt-auto flex flex-wrap items-center gap-2 pt-3">
        <select
          value={lead.category ?? ""}
          onChange={(e) => onCategory(lead, e.target.value as LeadCategory)}
          disabled={busy}
          aria-label={`Lead type for ${lead.contact_name || lead.contact_id}`}
          className={`h-8 rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] font-semibold ${INK} ${FOCUS}`}
        >
          <option value="" disabled>
            No type
          </option>
          {LEAD_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {LEAD_CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>
        <select
          value={lead.stage}
          onChange={(e) => onMove(lead, e.target.value as LeadStage)}
          disabled={busy}
          aria-label={`Stage for ${lead.contact_name || lead.contact_id}`}
          className={`h-8 rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] font-semibold ${INK} ${FOCUS}`}
        >
          {STAGES.map((s) => (
            <option key={s} value={s}>
              {STAGE_LABEL[s]}
            </option>
          ))}
        </select>
        {lead.thread_key && (
          <Link
            href={`/dashboard/channels/inbox?channel=${encodeURIComponent(lead.channel_id)}&key=${encodeURIComponent(lead.thread_key)}`}
            className={`ui-btn rounded-lg bg-[var(--ui-ink)] px-3.5 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)] ${FOCUS}`}
          >
            Open chat
          </Link>
        )}
        {lead.contact_username && (
          <a
            href={`https://instagram.com/${lead.contact_username}`}
            target="_blank"
            rel="noopener noreferrer"
            className={`rounded-[8px] border border-[var(--ui-line)] px-3 py-2 text-[12px] font-semibold ${INK} ${FOCUS}`}
          >
            Profile
          </a>
        )}
      </div>
    </li>
  );
}

export default function LeadsBoard({ platform }: { platform?: string }) {
  const queryClient = useQueryClient();
  const [priorityFirst, setPriorityFirst] = useState(true);
  const [stageFilter, setStageFilter] = useState<"all" | LeadStage>("all");
  const [categoryFilter, setCategoryFilter] = useState<"all" | LeadCategory>("all");
  const [priorityFilter, setPriorityFilter] = useState<"all" | "important">("all");
  const [channelFilter, setChannelFilter] = useState<string>("all");
  const [age, setAge] = useState<AgeKey>("any");
  const [busyId, setBusyId] = useState<string | null>(null);
  // Captured per fetch (Date.now is impure — hooks must not call it during
  // render), so age filters and countdowns share one consistent clock read.

  const leadsQuery = useQuery({
    queryKey: queryKeys.leads.list(platform, priorityFirst),
    queryFn: async () => {
      const data = await fetchLeads({ platform, limit: 200, priorityFirst });
      return { leads: data.leads ?? [], now: Date.now() };
    },
    staleTime: 30 * 1000,
  });
  const leads = leadsQuery.data?.leads ?? null;
  const now = leadsQuery.data?.now ?? 0;
  const error = leadsQuery.isError
    ? leadsQuery.error instanceof Error
      ? leadsQuery.error.message
      : "Could not load leads."
    : null;

  const move = async (lead: Lead, stage: LeadStage) => {
    if (stage === lead.stage || busyId) return;
    setBusyId(lead.id);
    try {
      const updated = await updateLead(lead.id, { stage });
      queryClient.setQueryData(queryKeys.leads.list(platform, priorityFirst), (old: { leads: Lead[]; now: number } | undefined) =>
        old ? { ...old, leads: (old.leads ?? []).map((r) => (r.id === updated.id ? updated : r)) } : old,
      );
    } catch {
      void queryClient.invalidateQueries({ queryKey: queryKeys.leads.all() });
    } finally {
      setBusyId(null);
    }
  };
  const changeCategory = async (lead: Lead, category: LeadCategory) => {
    if (category === lead.category || busyId) return;
    setBusyId(lead.id);
    try {
      const updated = await updateLead(lead.id, { category });
      queryClient.setQueryData(queryKeys.leads.list(platform, priorityFirst), (old: { leads: Lead[]; now: number } | undefined) =>
        old ? { ...old, leads: (old.leads ?? []).map((r) => (r.id === updated.id ? updated : r)) } : old,
      );
    } catch {
      void queryClient.invalidateQueries({ queryKey: queryKeys.leads.all() });
    } finally {
      setBusyId(null);
    }
  };
  const base = useMemo(() => {
    let rows = leads ?? [];
    if (!platform && channelFilter !== "all") {
      rows = rows.filter((l) => l.platform === channelFilter);
    }
    const ageDef = AGES.find((a) => a.key === age);
    if (ageDef?.days != null && now > 0) {
      const cutoff = now - ageDef.days * 86_400_000;
      rows = rows.filter((l) => new Date(l.created_at).getTime() >= cutoff);
    }
    return rows;
  }, [leads, platform, channelFilter, age, now]);

  const counts = useMemo(() => {
    const c: Record<LeadStage, number> = { new: 0, qualified: 0, follow_up: 0, converted: 0, lost: 0 };
    for (const lead of base) c[lead.stage] += 1;
    return c;
  }, [base]);

  // Counted against the same narrowed set as the stage chips, so the number
  // always describes what the other filters can actually show.
  const importantCount = useMemo(
    () => base.filter((l) => l.priority === "important").length,
    [base],
  );

  const channelCounts = useMemo(() => {
    const ageDef = AGES.find((a) => a.key === age);
    const c: Record<string, number> = {};
    for (const lead of leads ?? []) {
      if (ageDef?.days != null && now > 0 && new Date(lead.created_at).getTime() < now - ageDef.days * 86_400_000) {
        continue;
      }
      c[lead.platform] = (c[lead.platform] ?? 0) + 1;
    }
    return c;
  }, [leads, age, now]);

  // Virtualization hooks must run unconditionally (before any early return).
  const gridRef = useRef<HTMLDivElement>(null);
  const [cols, setCols] = useState(3);
  useEffect(() => {
    const el = gridRef.current;
    if (!el) return;
    const update = () => {
      const w = el.clientWidth;
      setCols(w >= 1024 ? 3 : w >= 640 ? 2 : 1);
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const rowCount = Math.ceil(base.length / cols);
  const rowVirtualizer = useVirtualizer({
    count: rowCount,
    getScrollElement: () => gridRef.current,
    estimateSize: () => 260,
    overscan: 2,
  });

  if (error) {
    return (
      <div role="alert" className={`mt-4 rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4 text-[13px] font-bold ${INK}`}>
        {error}
        <button
          type="button"
          onClick={() => {
            void queryClient.invalidateQueries({ queryKey: queryKeys.leads.all() });
          }}
          className={`ui-btn mt-3 block rounded-lg bg-[var(--ui-surface)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-ink)] ${FOCUS}`}
        >
          Try again
        </button>
      </div>
    );
  }

  if (leads === null) {
    return <p className={`mt-4 text-[13px] ${INK2}`}>Loading leads…</p>;
  }

  // Plain computation, not useMemo: this sits after the error/loading early
  // returns, and a hook there would violate the Rules of Hooks. n is capped at
  // 200 by the fetch, so the sort is free.
  let rows = stageFilter === "all" ? base : base.filter((l) => l.stage === stageFilter);
  if (categoryFilter !== "all") {
    rows = rows.filter((l) => l.category === categoryFilter);
  }
  if (priorityFilter === "important") {
    rows = rows.filter((l) => l.priority === "important");
  }
  // Always surface escalated (important) leads first, then recency.
  rows = [...rows].sort((a, b) => {
    const rank = (l: Lead) => (l.priority === "important" ? 0 : 1);
    return rank(a) - rank(b) || +new Date(b.updated_at) - +new Date(a.updated_at);
  });
  const visible = rows;


  return (
    <>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div
          className="flex gap-1 rounded-[8px] bg-[var(--ui-sunken)] p-0.5"
          role="group"
          aria-label="Filter leads by escalation priority"
        >
          {(["all", "important"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setPriorityFilter(key)}
              aria-pressed={priorityFilter === key}
              className={`rounded-[6px] border px-3 py-1 text-[12px] font-semibold ${FOCUS} ${
                priorityFilter === key
                  ? `border-[var(--ui-line)] bg-[var(--ui-surface)] ${INK}`
                  : `border-transparent ${INK2} hover:text-[var(--ui-ink)]`
              }`}
            >
              {key === "all" ? "All priority" : "Important"}
              {key === "important" && importantCount > 0 && (
                <span className="ml-1 tabular-nums">{importantCount}</span>
              )}
            </button>
          ))}
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-[12px] font-semibold text-ink/60">
          <input
            type="checkbox"
            checked={priorityFirst}
            onChange={(e) => setPriorityFirst(e.target.checked)}
            className={`h-3.5 w-3.5 rounded accent-[var(--ui-ink)] ${FOCUS}`}
          />
          Escalated first
        </label>

        <div
          className="flex gap-1 rounded-[8px] bg-[var(--ui-sunken)] p-0.5"
          role="group"
          aria-label="Filter leads by status"
        >
          {(["all", ...STAGES] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setStageFilter(key)}
              aria-pressed={stageFilter === key}
              className={`rounded-[6px] border px-3 py-1 text-[12px] font-semibold ${FOCUS} ${
                stageFilter === key
                  ? `border-[var(--ui-line)] bg-[var(--ui-surface)] ${INK}`
                  : `border-transparent ${INK2} hover:text-[var(--ui-ink)]`
              }`}
            >
              {key === "all" ? "All" : STAGE_LABEL[key]}
              {key !== "all" && counts[key] > 0 && (
                <span className="ml-1 tabular-nums">{counts[key]}</span>
              )}
            </button>
          ))}
        </div>

        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value as "all" | LeadCategory)}
          aria-label="Filter leads by type"
          className={`h-8 rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] font-semibold ${INK} ${FOCUS}`}
        >
          <option value="all">All lead types</option>
          {LEAD_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {LEAD_CATEGORY_LABELS[c]}
            </option>
          ))}
        </select>

        {!platform && (
          <div
            className="flex gap-1 rounded-[8px] bg-[var(--ui-sunken)] p-0.5"
            role="group"
            aria-label="Filter leads by channel"
          >
            <button
              type="button"
              onClick={() => setChannelFilter("all")}
              aria-pressed={channelFilter === "all"}
              className={`rounded-[6px] border px-3 py-1 text-[12px] font-semibold ${FOCUS} ${
                channelFilter === "all"
                  ? `border-[var(--ui-line)] bg-[var(--ui-surface)] ${INK}`
                  : `border-transparent ${INK2} hover:text-[var(--ui-ink)]`
              }`}
            >
              All channels
            </button>
            {CHANNELS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setChannelFilter(c)}
                aria-pressed={channelFilter === c}
                className={`flex items-center gap-1.5 rounded-[6px] border px-3 py-1 text-[12px] font-semibold ${FOCUS} ${
                  channelFilter === c
                    ? `border-[var(--ui-line)] bg-[var(--ui-surface)] ${INK}`
                    : `border-transparent ${INK2} hover:text-[var(--ui-ink)]`
                }`}
              >
                <PlatformMark platform={c} size={12} />
                {platformLabel(c)}
                {(channelCounts[c] ?? 0) > 0 && (
                  <span className="tabular-nums">{channelCounts[c]}</span>
                )}
              </button>
            ))}
          </div>
        )}

        <select
          value={age}
          onChange={(e) => setAge(e.target.value as AgeKey)}
          aria-label="Filter leads by age"
          className={`ml-auto h-8 rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] font-semibold ${INK} ${FOCUS}`}
        >
          {AGES.map((a) => (
            <option key={a.key} value={a.key}>
              {a.label}
            </option>
          ))}
        </select>
        <span className={`text-[12px] tabular-nums ${INK2}`}>{base.length}</span>
      </div>

      {visible.length === 0 ? (
        <p className={`mt-6 text-[13px] ${INK2}`}>
          {priorityFilter === "important"
            ? "No escalated leads. Nothing here needs a human right now."
            : "No leads in this view."}
        </p>
      ) : (
        <div
          ref={gridRef}
          className="mt-3 max-h-[70vh] overflow-y-auto"
        >
          <div style={{ height: rowVirtualizer.getTotalSize(), position: "relative", width: "100%" }}>
            {rowVirtualizer.getVirtualItems().map((vi) => {
              const start = vi.index * cols;
              const rowItems = visible.slice(start, start + cols);
              return (
                <div
                  key={vi.index}
                  data-index={vi.index}
                  ref={rowVirtualizer.measureElement}
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vi.start}px)` }}
                  className={`grid gap-3 ${cols === 3 ? "lg:grid-cols-3" : cols === 2 ? "lg:grid-cols-2" : "grid-cols-1"}`}
                >
                  {rowItems.map((lead) => (
                    <LeadCard
                      key={lead.id}
                      lead={lead}
                      busy={busyId === lead.id}
                      onMove={move}
                      onCategory={changeCategory}
                    />
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </>
  );
}
