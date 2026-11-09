"use client";

import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import LogoLoader from "@/components/LogoLoader";
import {
  fetchMemories,
  fetchMemorySettings,
  updateMemory,
  updateMemorySettings,
  type Memory,
  type MemoryStatus,
} from "@/lib/api-memory";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

type MemoryDict = Dict["memory"];

/*
 * The review queue for cumulative memory.
 *
 * A resolve drafts one scrubbed lesson. Nothing here reaches a customer until
 * a human approves it; approving is the moment a conversation becomes a
 * reusable business fact. The page is deliberately a queue, not a knowledge
 * editor: every card is one conversation's lesson, with provenance reduced to
 * an outcome and facts.
 */

const TABS: { key: MemoryStatus | "all" }[] = [
  { key: "pending" },
  { key: "approved" },
  { key: "rejected" },
  { key: "all" },
];

function StatusChip({ status }: { status: MemoryStatus }) {
  const { t } = useI18n();
  const mm = t.memory;
  const style =
    status === "approved"
      ? "bg-emerald-50 text-emerald-800 border-emerald-200"
      : status === "rejected"
        ? "bg-[var(--ui-sunken)] text-[var(--ui-ink-2)] border-[var(--ui-line)]"
        : "bg-amber-50 text-amber-800 border-amber-200";
  return (
    <span
      className={`rounded-full border px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${style}`}
    >
      {mm.status[status]}
    </span>
  );
}

function MemoryCard({
  memory,
  busy,
  onAct,
}: {
  memory: Memory;
  busy: boolean;
  onAct: (id: string, patch: Parameters<typeof updateMemory>[1]) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [summary, setSummary] = useState(memory.summary);
  const [outcome, setOutcome] = useState(memory.outcome ?? "");
  const [facts, setFacts] = useState((memory.facts ?? []).join("\n"));
  const { t, locale } = useI18n();
  const mm = t.memory;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";

  useEffect(() => {
    setSummary(memory.summary);
    setOutcome(memory.outcome ?? "");
    setFacts((memory.facts ?? []).join("\n"));
  }, [memory]);

  const save = () => {
    onAct(memory.id, {
      summary: summary.trim(),
      outcome: outcome.trim(),
      facts: facts
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean),
    });
    setEditing(false);
  };

  return (
    <article className="rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={memory.status} />
        {memory.outcome && (
          <span className="text-[12px] font-semibold text-[var(--ui-ink)]">
            {memory.outcome}
          </span>
        )}
        <time className="ml-auto text-[11px] text-[var(--ui-ink-2)]">
          {new Date(memory.created_at).toLocaleString(dateLocale)}
        </time>
      </div>

      {editing ? (
        <div className="mt-3 space-y-2">
          <label className="block text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
            {mm.summaryLabel}
            <textarea
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              rows={4}
              className="mt-1 w-full rounded-lg border border-[var(--ui-line)] bg-[var(--ui-page)] px-3 py-2 text-[13px] font-normal text-[var(--ui-ink)]"
            />
          </label>
          <label className="block text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
            {mm.outcomeLabel}
            <input
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
              className="mt-1 w-full rounded-lg border border-[var(--ui-line)] bg-[var(--ui-page)] px-3 py-2 text-[13px] font-normal text-[var(--ui-ink)]"
            />
          </label>
          <label className="block text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
            {mm.factsLabel}
            <textarea
              value={facts}
              onChange={(e) => setFacts(e.target.value)}
              rows={4}
              className="mt-1 w-full rounded-lg border border-[var(--ui-line)] bg-[var(--ui-page)] px-3 py-2 text-[13px] font-normal text-[var(--ui-ink)]"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled={busy || !summary.trim()}
              onClick={save}
              className="rounded-full bg-[var(--ui-ink)] px-4 py-1.5 text-[11px] font-bold text-[var(--ui-on-ink)] disabled:opacity-40"
            >
              {mm.saveChanges}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-full border border-[var(--ui-line)] px-4 py-1.5 text-[11px] font-semibold text-[var(--ui-ink)]"
            >
              {mm.cancelBtn}
            </button>
            {memory.status === "approved" && (
              <span className="text-[11px] text-amber-700">
                {mm.liveNote}
              </span>
            )}
          </div>
        </div>
      ) : (
        <>
          <p className="mt-2 whitespace-pre-line text-[13px] leading-relaxed text-[var(--ui-ink)]">
            {memory.summary}
          </p>
          {memory.facts.length > 0 && (
            <div className="mt-3 rounded-xl bg-[var(--ui-sunken)] p-3">
              <p className="text-[10px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">
                {mm.factsTitle}
              </p>
              <ul className="mt-1.5 space-y-1">
                {memory.facts.map((fact) => (
                  <li
                    key={fact}
                    className="flex gap-1.5 text-[12px] leading-snug text-[var(--ui-ink)]"
                  >
                    <span aria-hidden className="text-[var(--ui-ink-2)]">
                      —
                    </span>
                    <span>{fact}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {!editing && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {memory.status !== "approved" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onAct(memory.id, { status: "approved" })}
              className="rounded-full bg-emerald-600 px-4 py-1.5 text-[11px] font-bold text-white disabled:opacity-40"
            >
              {busy ? mm.saving : mm.approve}
            </button>
          )}
          {memory.status !== "rejected" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onAct(memory.id, { status: "rejected" })}
              className="rounded-full border border-[var(--ui-line)] px-4 py-1.5 text-[11px] font-semibold text-[var(--ui-ink)] disabled:opacity-40"
            >
              {mm.reject}
            </button>
          )}
          {memory.status !== "pending" && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onAct(memory.id, { status: "pending" })}
              className="rounded-full border border-[var(--ui-line)] px-4 py-1.5 text-[11px] font-semibold text-[var(--ui-ink)] disabled:opacity-40"
            >
              {mm.reopen}
            </button>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => setEditing(true)}
            className="rounded-full border border-[var(--ui-line)] px-4 py-1.5 text-[11px] font-semibold text-[var(--ui-ink)] disabled:opacity-40"
          >
            {mm.editBtn}
          </button>
        </div>
      )}
    </article>
  );
}

export default function MemoryPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<MemoryStatus | "all">("pending");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { t, locale } = useI18n();
  const mm: MemoryDict = t.memory;
  const dateLocale = locale === "ar" ? "ar-SA" : "en-US";
  const fmt = (n: number) => new Intl.NumberFormat(dateLocale).format(n);

  const listQuery = useQuery({
    queryKey: ["memory", "list", tab],
    queryFn: () => fetchMemories(tab),
    staleTime: 15_000,
  });
  const settingsQuery = useQuery({
    queryKey: ["memory", "settings"],
    queryFn: fetchMemorySettings,
    staleTime: 60_000,
  });

  const memories = listQuery.data?.memories ?? [];
  const pending = listQuery.data?.pending_count ?? 0;
  const enabled = settingsQuery.data?.enabled ?? true;
  const loadError = listQuery.isError
    ? listQuery.error instanceof Error
      ? listQuery.error.message
      : mm.loadFail
    : null;

  const act = async (
    id: string,
    patch: Parameters<typeof updateMemory>[1],
  ) => {
    if (busyId) return;
    setBusyId(id);
    setError(null);
    try {
      await updateMemory(id, patch);
      await queryClient.invalidateQueries({ queryKey: ["memory"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : mm.updateFail);
    } finally {
      setBusyId(null);
    }
  };

  const toggleEnabled = async () => {
    setError(null);
    try {
      await updateMemorySettings(!enabled);
      await queryClient.invalidateQueries({ queryKey: ["memory"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : mm.settingFail);
    }
  };

  return (
    <div className="team-ui h-full overflow-y-auto px-4 py-6 sm:px-6">
      <div className="mx-auto max-w-4xl">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-[20px] font-bold text-[var(--ui-ink)]">{mm.title}</h1>
            <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-[var(--ui-ink-2)]">
              {mm.sub}
            </p>
          </div>
          <label className="flex cursor-pointer items-center gap-2 rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-ink)]">
            <input
              type="checkbox"
              checked={enabled}
              disabled={settingsQuery.isPending}
              onChange={() => void toggleEnabled()}
              className="h-3.5 w-3.5 accent-[var(--ui-ink)]"
            />
            {mm.learnLabel}
          </label>
        </div>

        {(error || loadError) && (
          <p
            role="alert"
            className="mt-4 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-[13px] font-medium text-red-800"
          >
            {error ?? loadError}
          </p>
        )}

        <div className="mt-5 flex flex-wrap items-center gap-1 rounded-xl bg-[var(--ui-sunken)] p-1">
          {TABS.map((tb) => (
            <button
              key={tb.key}
              type="button"
              onClick={() => setTab(tb.key)}
              aria-pressed={tab === tb.key}
              className={`rounded-lg px-3 py-1.5 text-[12px] font-semibold ${
                tab === tb.key
                  ? "bg-[var(--ui-surface)] text-[var(--ui-ink)]"
                  : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
              }`}
            >
              {mm.tabs[tb.key]}
              {tb.key === "pending" && pending > 0 ? ` (${fmt(pending)})` : ""}
            </button>
          ))}
        </div>

        {!enabled && (
          <p className="mt-4 rounded-xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-3 text-[12px] text-[var(--ui-ink-2)]">
            {mm.offNote}
          </p>
        )}

        {listQuery.isPending ? (
          <div className="flex justify-center py-16">
            <LogoLoader size={28} />
          </div>
        ) : memories.length === 0 ? (
          <div className="mt-4 rounded-2xl border border-[var(--ui-line)] bg-[var(--ui-surface)] px-6 py-12 text-center">
            <p className="text-[14px] font-bold text-[var(--ui-ink)]">
              {tab === "pending" ? mm.emptyPending : mm.emptyElse}
            </p>
            <p className="mx-auto mt-1 max-w-md text-[12px] leading-relaxed text-[var(--ui-ink-2)]">
              {mm.emptyBody}
            </p>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {memories.map((memory) => (
              <MemoryCard
                key={memory.id}
                memory={memory}
                busy={busyId === memory.id}
                onAct={act}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
