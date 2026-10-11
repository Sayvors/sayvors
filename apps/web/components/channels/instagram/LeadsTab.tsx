"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import PlatformMark from "@/components/channels/PlatformMark";
import { fetchLeads, updateLead, type Lead, type LeadStage } from "@/lib/api-leads";

/*
 * Leads tab: people the AI spotted in this account's DMs.
 *
 * Reads the stored /api/v1/leads rows — capture and follow-up scheduling
 * happen in the messaging pipeline, this tab only renders and moves a
 * lead through new -> qualified -> follow_up -> converted/lost. The
 * conversation itself lives in the unified inbox; every row deep-links
 * to its thread. Monochrome by weight: "new" is the ink-inverted chip
 * (it wants action), the rest sit on sunken.
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";
const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";
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

const FILTERS: { key: "all" | LeadStage; label: string }[] = [
  { key: "all", label: "All" },
  ...STAGES.map((s) => ({ key: s, label: STAGE_LABEL[s] })),
];

function Avatar({ lead }: { lead: Lead }) {
  if (lead.avatar_url) {
    return (
      <Image
        src={lead.avatar_url}
        alt=""
        width={40}
        height={40}
        className="h-10 w-10 shrink-0 rounded-full border border-[var(--ui-line)] object-cover"
        unoptimized
      />
    );
  }
  return (
    <span
      aria-hidden
      className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-[var(--ui-line)] bg-[var(--ui-sunken)]"
    >
      <PlatformMark platform="instagram" size={18} />
    </span>
  );
}

function timeAgo(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 60) return `${mins || 1}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export default function LeadsTab() {
  const [leads, setLeads] = useState<Lead[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | LeadStage>("all");
  const [busyId, setBusyId] = useState<string | null>(null);
  // Bumping this re-runs the fetch — the honest reset after a failed patch.
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchLeads({ platform: "instagram", limit: 200 }).then(
      (data) => {
        if (!cancelled) {
          setLeads(data.leads ?? []);
          setError(null);
        }
      },
      (e: unknown) => {
        if (!cancelled) {
          setLeads([]);
          setError(e instanceof Error ? e.message : "Could not load leads.");
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [reload]);

  const counts = useMemo(() => {
    const c: Record<LeadStage, number> = { new: 0, qualified: 0, follow_up: 0, converted: 0, lost: 0 };
    for (const lead of leads ?? []) c[lead.stage] += 1;
    return c;
  }, [leads]);

  const move = async (lead: Lead, stage: LeadStage) => {
    if (stage === lead.stage || busyId) return;
    setBusyId(lead.id);
    try {
      const updated = await updateLead(lead.id, { stage });
      setLeads((rows) => rows?.map((r) => (r.id === updated.id ? updated : r)) ?? rows);
    } catch {
      // The optimistic truth failed — refetch shows what the DB really has.
      setReload((n) => n + 1);
    } finally {
      setBusyId(null);
    }
  };

  if (error) {
    return (
      <div role="alert" className={`rounded-[8px] border border-[var(--ui-ink)] bg-[var(--ui-sunken)] p-4 text-[13px] font-bold ${INK}`}>
        {error}
        <button
          type="button"
          onClick={() => {
            setLeads(null);
            setError(null);
            setReload((n) => n + 1);
          }}
          className={`ui-btn mt-3 block rounded-lg bg-[var(--ui-surface)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-ink)] ${FOCUS}`}
        >
          Try again
        </button>
      </div>
    );
  }

  if (leads === null) {
    return <p className={`text-[13px] ${INK2}`}>Loading leads…</p>;
  }

  if (leads.length === 0) {
    return (
      <div className={PANEL}>
        <h3 className={`text-[15px] font-semibold ${INK}`}>No leads yet</h3>
        <p className={`mt-2 text-[13px] ${INK2}`}>
          When the AI spots someone interested in your services in your DMs, they
          show up here automatically — with what they need, ready to follow up.
        </p>
      </div>
    );
  }

  const visible = filter === "all" ? leads : leads.filter((l) => l.stage === filter);

  return (
    <section className={PANEL}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className={`text-[15px] font-semibold ${INK}`}>Leads</h3>
          <p className={`mt-1 text-[12px] ${INK2}`}>
            Spotted by the AI in your DMs. The full conversations live in the{" "}
            <Link href="/dashboard/channels/inbox" className="underline underline-offset-2">
              inbox
            </Link>
            .
          </p>
        </div>
        <div
          className="flex gap-1 rounded-[8px] bg-[var(--ui-sunken)] p-0.5"
          role="group"
          aria-label="Filter leads"
        >
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              aria-pressed={filter === f.key}
              className={`rounded-[6px] border px-3 py-1 text-[12px] font-semibold ${FOCUS} ${
                filter === f.key
                  ? `border-[var(--ui-line)] bg-[var(--ui-surface)] ${INK}`
                  : `border-transparent ${INK2} hover:text-[var(--ui-ink)]`
              }`}
            >
              {f.label}
              {f.key !== "all" && counts[f.key] > 0 && (
                <span className="ml-1 tabular-nums">{counts[f.key]}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <p className={`mt-6 text-[13px] ${INK2}`}>No leads in this view.</p>
      ) : (
        <ul className="mt-4">
          {visible.map((lead) => (
            <li
              key={lead.id}
              className="flex flex-wrap items-center gap-3 border-b border-[var(--ui-line)] py-3 last:border-0"
            >
              <Avatar lead={lead} />
              <div className="min-w-[12rem] flex-1">
                <p className={`flex items-center gap-2 text-[13px] font-semibold ${INK}`}>
                  {lead.contact_name ||
                    (lead.contact_username ? `@${lead.contact_username}` : "Instagram user")}
                  <span
                    className={`rounded-[8px] px-2 py-0.5 text-[11px] font-bold ${STAGE_CHIP[lead.stage]}`}
                  >
                    {STAGE_LABEL[lead.stage]}
                  </span>
                  {lead.opt_out && (
                    <span className="rounded-[8px] border border-[var(--ui-line)] px-2 py-0.5 text-[11px] font-semibold text-[var(--ui-ink-2)]">
                      Opted out
                    </span>
                  )}
                </p>
                <p className={`mt-0.5 line-clamp-1 text-[12px] ${INK2}`}>
                  {lead.summary || "No summary captured yet."}
                </p>
              </div>
              <time
                dateTime={lead.created_at}
                title={new Date(lead.created_at).toLocaleString()}
                className={`shrink-0 text-[12px] tabular-nums ${INK2}`}
              >
                {timeAgo(lead.created_at)}
              </time>
              <div className="flex shrink-0 items-center gap-2">
                <select
                  value={lead.stage}
                  onChange={(e) => move(lead, e.target.value as LeadStage)}
                  disabled={busyId === lead.id}
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
                    className={`ui-btn rounded-lg bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)] ${FOCUS}`}
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
          ))}
        </ul>
      )}
    </section>
  );
}
