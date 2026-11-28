"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  addEnterpriseRecipient,
  decideBillingRequest,
  fetchBillingRequests,
  fetchEnterpriseRecipients,
  removeEnterpriseRecipient,
  type AdminBillingRequest,
  type EnterpriseRecipient,
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

  const [recipients, setRecipients] = useState<EnterpriseRecipient[]>([]);
  const [maxRecipients, setMaxRecipients] = useState(25);
  const [recipientsLoading, setRecipientsLoading] = useState(true);
  const [recipientBusy, setRecipientBusy] = useState<string | null>(null);
  const [recipientError, setRecipientError] = useState<string | null>(null);
  const [recipientNotice, setRecipientNotice] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");

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

  const loadRecipients = useCallback(async () => {
    setRecipientsLoading(true);
    setRecipientError(null);
    try {
      const data = await fetchEnterpriseRecipients();
      setRecipients(data.items);
      setMaxRecipients(data.max_recipients);
    } catch (e) {
      setRecipientError(
        e instanceof Error ? e.message : "Could not load the notification list.",
      );
    } finally {
      setRecipientsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRecipients();
  }, [loadRecipients]);

  const addRecipient = async (event: React.FormEvent) => {
    event.preventDefault();
    const email = newEmail.trim();
    if (!email) return;
    setRecipientBusy("add");
    setRecipientError(null);
    setRecipientNotice(null);
    try {
      const created = await addEnterpriseRecipient(email);
      setRecipients((prev) => [...prev, created]);
      setNewEmail("");
      setRecipientNotice(`${created.email} will now be emailed about Enterprise requests.`);
    } catch (e) {
      setRecipientError(e instanceof Error ? e.message : "Could not add the address.");
    } finally {
      setRecipientBusy(null);
    }
  };

  const removeRecipient = async (row: EnterpriseRecipient) => {
    if (!window.confirm(`Stop emailing ${row.email} about Enterprise requests?`)) return;
    setRecipientBusy(row.id);
    setRecipientError(null);
    setRecipientNotice(null);
    try {
      await removeEnterpriseRecipient(row.id);
      setRecipients((prev) => prev.filter((item) => item.id !== row.id));
      setRecipientNotice(`${row.email} was removed from the notification list.`);
    } catch (e) {
      setRecipientError(e instanceof Error ? e.message : "Could not remove the address.");
    } finally {
      setRecipientBusy(null);
    }
  };

  const pendingCount = useMemo(
    () => items.filter((request) => request.status === "pending").length,
    [items],
  );

  async function decide(request: AdminBillingRequest, approve: boolean) {
    if (approve && request.kind === "plan" && !window.confirm(
      "Approve this plan request? The plan's included AI credit will be granted once when the plan changes.",
    )) return;
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

      <section className="panel mt-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-[15px] font-bold text-ink">Enterprise request emails</h2>
            <p className="mt-0.5 max-w-2xl text-[11.5px] leading-relaxed text-ink/50">
              When a tenant asks for the Enterprise plan, every address on this list
              receives an email with the tenant&apos;s contact details so sales can follow
              up by email, phone or a meeting.
            </p>
          </div>
          <span className="rounded-full bg-ink/[0.05] px-2.5 py-1 text-[10.5px] font-bold uppercase tracking-wide text-ink/55">
            {recipients.length} / {maxRecipients}
          </span>
        </div>

        <form onSubmit={addRecipient} className="mt-3 flex flex-wrap items-center gap-2">
          <input
            type="email"
            required
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            maxLength={320}
            placeholder="sales@example.com"
            aria-label="Email address to add"
            className="input-field h-9 max-w-sm flex-1"
          />
          <button
            type="submit"
            disabled={recipientBusy !== null || recipients.length >= maxRecipients}
            className={`btn-primary !px-3 !py-1.5 disabled:opacity-50 ${FOCUS_RING}`}
          >
            {recipientBusy === "add" ? "Adding…" : "Add address"}
          </button>
        </form>

        {recipientError && (
          <p role="alert" className="mt-3 rounded-[2px] border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">
            {recipientError}
          </p>
        )}
        {recipientNotice && (
          <p role="status" className="mt-3 rounded-[2px] border border-emerald-200 bg-emerald-50 px-3 py-2 text-[12px] font-medium text-emerald-800">
            {recipientNotice}
          </p>
        )}

        {recipientsLoading ? (
          <div className="mt-3 space-y-2" aria-hidden>
            {[0, 1].map((i) => (
              <div key={i} className="h-9 animate-pulse rounded-[2px] bg-ink/[0.05]" />
            ))}
          </div>
        ) : recipients.length === 0 ? (
          <p className="mt-3 rounded-[2px] border border-dashed border-amber-300 bg-amber-50/60 px-3 py-2.5 text-[11.5px] font-medium text-amber-800">
            No one is emailed yet. Add at least one address so Enterprise requests reach sales.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-ink/[0.05] rounded-[2px] border border-[var(--ui-line)]">
            {recipients.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink/85" title={row.email}>
                  {row.email}
                </span>
                {row.created_at && (
                  <span className="text-[10.5px] text-ink/40">
                    added {new Date(row.created_at).toLocaleDateString()}
                    {row.created_by ? ` by ${row.created_by}` : ""}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => void removeRecipient(row)}
                  disabled={recipientBusy !== null}
                  className={`rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1 text-[10.5px] font-semibold text-ink/60 transition hover:border-coral hover:text-coral disabled:opacity-40 ${FOCUS_RING}`}
                >
                  {recipientBusy === row.id ? "Removing…" : "Remove"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

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
