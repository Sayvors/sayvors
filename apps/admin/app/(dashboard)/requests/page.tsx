"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  decideBillingRequest,
  fetchBillingRequests,
  type AdminBillingRequest,
} from "@/lib/admin-api";

type Filter = "pending" | "approved" | "rejected" | "all";

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

const KIND_LABEL: Record<string, string> = {
  messages: "WhatsApp messages",
  channels: "Channels",
  ai_credit: "AI credit",
  plan: "Plan",
};

function fmtCents(cents: number | null): string {
  return `$${((cents ?? 0) / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function summary(request: AdminBillingRequest): string {
  if (request.kind === "ai_credit") return fmtCents(request.amount);
  if (request.kind === "plan") return `Plan: ${request.plan_slug ?? "—"}`;
  if (request.kind === "messages") return `+${(request.amount ?? 0).toLocaleString()} messages/month`;
  return `+${(request.amount ?? 0).toLocaleString()} channels`;
}

export default function AdminRequestsPage() {
  const [filter, setFilter] = useState<Filter>("pending");
  const [items, setItems] = useState<AdminBillingRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await fetchBillingRequests(filter));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load requests.");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const pendingCount = useMemo(
    () => items.filter((request) => request.status === "pending").length,
    [items],
  );

  async function decide(request: AdminBillingRequest, approve: boolean) {
    setBusy(request.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await decideBillingRequest(request.id, approve, notes[request.id]);
      setNotice(
        `${KIND_LABEL[updated.kind] ?? updated.kind} request ${updated.status}.${
          updated.decision_note ? ` ${updated.decision_note}` : ""
        }`,
      );
      setItems((prev) =>
        filter === "pending" ? prev.filter((row) => row.id !== request.id) : prev.map((row) => (row.id === request.id ? updated : row)),
      );
      setNotes((prev) => ({ ...prev, [request.id]: "" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Decision failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Top-up &amp; plan requests</h1>
          <p className="mt-1 text-[12px] text-ink/50">
            Approving applies the purchase with the same grant path as a manual admin change.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {(["pending", "approved", "rejected", "all"] as Filter[]).map((value) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={`rounded-[2px] px-3 py-1.5 text-[11px] font-semibold capitalize transition ${
                filter === value
                  ? "bg-deep-violet text-white"
                  : "border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] text-ink/60 hover:border-deep-violet hover:text-deep-violet"
              } ${FOCUS_RING}`}
            >
              {value}
              {value === "pending" && pendingCount > 0 ? ` (${pendingCount})` : ""}
            </button>
          ))}
          <button
            onClick={() => void load()}
            className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet hover:text-deep-violet ${FOCUS_RING}`}
          >
            Refresh
          </button>
        </div>
      </div>

      {(error || notice) && (
        <p
          role="status"
          className={`mt-4 rounded-[2px] px-3 py-2.5 text-[12px] leading-relaxed ${
            error ? "border border-amber-200 bg-amber-50 text-amber-800" : "border border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {error ?? notice}
        </p>
      )}

      {loading ? (
        <div className="mt-6 space-y-2" aria-hidden>
          {[1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-[2px] bg-ink/[0.04]" />)}
        </div>
      ) : items.length === 0 ? (
        <p className="mt-6 rounded-[2px] border border-dashed border-[var(--ui-line-strong)] p-8 text-center text-[12px] text-ink/45">
          No {filter === "all" ? "" : filter} requests.
        </p>
      ) : (
        <ul className="mt-6 space-y-3">
          {items.map((request) => (
            <li key={request.id} className="panel p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-[13px] font-bold text-ink">
                    {KIND_LABEL[request.kind] ?? request.kind}
                    <span className="ml-2 font-medium text-ink/55">{summary(request)}</span>
                  </p>
                  <p className="mt-0.5 text-[11.5px] text-ink/50">
                    {request.email ?? request.tenant_id}
                    <span className="mx-1.5">·</span>
                    {request.created_at ? new Date(request.created_at).toLocaleString() : "—"}
                  </p>
                  {request.note && (
                    <p className="mt-1.5 rounded-[2px] bg-ink/[0.03] px-2.5 py-1.5 text-[11.5px] text-ink/60">
                      “{request.note}”
                    </p>
                  )}
                  {request.status !== "pending" && (
                    <p className="mt-1.5 text-[11px] text-ink/45">
                      {request.status} by {request.reviewed_by ?? "admin"}
                      {request.decision_note ? ` · ${request.decision_note}` : ""}
                    </p>
                  )}
                </div>
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
                    request.status === "approved"
                      ? "bg-emerald-100 text-emerald-700"
                      : request.status === "rejected"
                        ? "bg-red-100 text-red-700"
                        : "bg-amber-100 text-amber-700"
                  }`}
                >
                  {request.status}
                </span>
              </div>

              {request.status === "pending" && (
                <div className="mt-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
                  <input
                    value={notes[request.id] ?? ""}
                    onChange={(e) => setNotes((prev) => ({ ...prev, [request.id]: e.target.value }))}
                    maxLength={500}
                    placeholder="Decision note (optional)"
                    aria-label="Decision note"
                    className="h-9 rounded-[2px] border border-[var(--ui-line)] bg-white px-2.5 text-[12px] text-ink outline-none focus:border-deep-violet"
                  />
                  <button
                    onClick={() => void decide(request, true)}
                    disabled={busy !== null}
                    className={`rounded-[2px] bg-emerald-600 px-3 py-2 text-[11.5px] font-bold text-white transition hover:bg-emerald-700 disabled:opacity-50 ${FOCUS_RING}`}
                  >
                    {busy === request.id ? "Working…" : "Approve"}
                  </button>
                  <button
                    onClick={() => void decide(request, false)}
                    disabled={busy !== null}
                    className={`rounded-[2px] border border-red-300 bg-white px-3 py-2 text-[11.5px] font-bold text-red-700 transition hover:bg-red-600 hover:text-white disabled:opacity-50 ${FOCUS_RING}`}
                  >
                    Reject
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
