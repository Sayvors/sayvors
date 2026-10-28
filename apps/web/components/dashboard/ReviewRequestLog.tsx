"use client";

import { useCallback, useEffect, useState } from "react";
import {
  cancelReviewRequest,
  fetchReviewRequests,
  retryFailedReviewRequests,
  retryReviewRequest,
  type ReviewRequestItem,
  type ReviewRequestList,
} from "@/lib/api-analytics";

const STATUS_STYLE: Record<string, string> = {
  queued: "bg-amber-100 text-amber-700",
  sent: "bg-emerald-100 text-emerald-700",
  delivered: "bg-emerald-100 text-emerald-700",
  clicked: "bg-sky-100 text-sky-700",
  reviewed: "bg-deep-violet/10 text-deep-violet",
  failed: "bg-coral/10 text-coral",
  cancelled: "bg-ink/10 text-ink/50",
};

const PAGE = 25;

export default function ReviewRequestLog() {
  const [data, setData] = useState<ReviewRequestList | null>(null);
  const [status, setStatus] = useState("");
  const [channel, setChannel] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const res = await fetchReviewRequests({
        status: status || undefined,
        channel: channel || undefined,
        q: q.trim() || undefined,
        limit: PAGE,
        offset,
      });
      setData(res);
    } catch {
      setMessage("Could not load the request log.");
    } finally {
      setBusy(false);
    }
  }, [status, channel, q, offset]);

  useEffect(() => {
    void load();
  }, [load]);

  const retryOne = async (row: ReviewRequestItem) => {
    setMessage(null);
    try {
      await retryReviewRequest(row.id);
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message.slice(0, 160) : "Retry failed.");
    }
  };

  const retryAll = async () => {
    setMessage(null);
    try {
      const res = await retryFailedReviewRequests();
      setMessage(`${res.retried} failed request${res.retried === 1 ? "" : "s"} queued for retry.`);
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message.slice(0, 160) : "Retry failed.");
    }
  };

  const cancelOne = async (row: ReviewRequestItem) => {
    setMessage(null);
    try {
      await cancelReviewRequest(row.id);
      await load();
    } catch (e) {
      setMessage(e instanceof Error ? e.message.slice(0, 160) : "Cancel failed.");
    }
  };

  const counts = data?.counts ?? {};
  const failed = counts.failed ?? 0;

  return (
    <section className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.08] dark:bg-ink">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-[14px] font-bold text-ink dark:text-fog">Request log</h3>
          <p className="mt-0.5 text-[11px] text-ink/50 dark:text-fog/50">
            Every bulk and single request, with its delivery status. Retry failed rows individually or all at once.
          </p>
        </div>
        {failed > 0 && (
          <button
            onClick={() => void retryAll()}
            disabled={busy}
            className="rounded-lg bg-coral px-3 py-1.5 text-[11px] font-bold text-white transition hover:bg-coral/90 disabled:opacity-50"
          >
            Retry all failed ({failed})
          </button>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {(["queued", "sent", "clicked", "reviewed", "failed", "cancelled"] as const).map((s) => (
          <button
            key={s}
            onClick={() => { setStatus(status === s ? "" : s); setOffset(0); }}
            aria-pressed={status === s}
            className={`rounded-full px-2.5 py-1 text-[10px] font-bold capitalize transition ${
              status === s ? "bg-ink text-white dark:bg-fog dark:text-ink" : "bg-ink/[0.05] text-ink/60 dark:bg-fog/[0.08] dark:text-fog/60"
            }`}
          >
            {s} {counts[s] ? `(${counts[s]})` : ""}
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <select
          value={channel}
          onChange={(e) => { setChannel(e.target.value); setOffset(0); }}
          className="rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
        >
          <option value="">All channels</option>
          <option value="email">Email</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="in_person">In person</option>
        </select>
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
          placeholder="Search contact"
          className="min-w-[180px] flex-1 rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
        />
      </div>

      {message && <p className="mt-2 text-[11px] text-ink/60 dark:text-fog/60">{message}</p>}

      {data?.items.some(
        (r) => r.status === "failed" && r.channel === "whatsapp" && /24|template|window/i.test(r.error ?? "")
      ) && (
        <p className="mt-2 rounded-lg border border-amber-300/60 bg-amber-50 px-2.5 py-2 text-[10px] leading-relaxed text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          Some WhatsApp sends were rejected because the customer was outside the 24-hour window.
          Free-form WhatsApp asks only work inside that window; an approved template is required for cold sends.
        </p>
      )}

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="border-b border-ink/[0.06] text-[10px] uppercase tracking-wide text-ink/45 dark:border-fog/[0.08] dark:text-fog/45">
            <tr>
              <th className="px-2 py-1.5">Contact</th>
              <th className="px-2 py-1.5">Channel</th>
              <th className="px-2 py-1.5">Status</th>
              <th className="px-2 py-1.5">Sent</th>
              <th className="px-2 py-1.5">Detail</th>
              <th className="px-2 py-1.5 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {!data || data.items.length === 0 ? (
              <tr><td colSpan={6} className="px-2 py-8 text-center text-ink/40 dark:text-fog/40">{busy ? "Loading…" : "No requests yet."}</td></tr>
            ) : (
              data.items.map((r) => (
                <tr key={r.id} className="border-b border-ink/[0.04] last:border-0 dark:border-fog/[0.06]">
                  <td className="px-2 py-2">
                    <span className="block truncate text-ink dark:text-fog">{r.contact_name || r.contact || "-"}</span>
                    {r.contact_name && r.contact && <span className="block truncate text-[10px] text-ink/40 dark:text-fog/40">{r.contact}</span>}
                  </td>
                  <td className="px-2 py-2 capitalize text-ink/60 dark:text-fog/60">{r.channel.replace(/_/g, " ")}</td>
                  <td className="px-2 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold capitalize ${STATUS_STYLE[r.status] ?? "bg-ink/10 text-ink/50"}`}>
                      {r.status}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-[10px] text-ink/50 dark:text-fog/50">
                    {new Date(r.sent_at).toLocaleString()}
                  </td>
                  <td className="max-w-[220px] px-2 py-2 text-[10px] text-ink/50 dark:text-fog/50">
                    {r.status === "failed" ? (
                      <span className="text-coral" title={r.error ?? ""}>{r.error ?? "Send failed"}</span>
                    ) : r.clicked_at ? (
                      `clicked ${new Date(r.clicked_at).toLocaleDateString()}`
                    ) : (
                      r.sent_via ?? "-"
                    )}
                  </td>
                  <td className="px-2 py-2 text-right">
                    {r.status === "failed" && (
                      <button onClick={() => void retryOne(r)} className="text-[10px] font-bold text-deep-violet hover:underline">
                        Retry
                      </button>
                    )}
                    {r.status === "queued" && (
                      <button onClick={() => void cancelOne(r)} className="text-[10px] font-bold text-ink/50 hover:underline dark:text-fog/50">
                        Cancel
                      </button>
                    )}
                    {r.link && (r.status === "sent" || r.status === "clicked") && (
                      <a href={r.link} target="_blank" rel="noreferrer" className="ml-2 text-[10px] font-bold text-deep-violet hover:underline">
                        Link
                      </a>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <button
          onClick={() => setOffset(Math.max(0, offset - PAGE))}
          disabled={offset === 0 || busy}
          className="rounded-lg border border-ink/[0.08] px-3 py-1.5 text-[11px] font-semibold text-ink/70 disabled:opacity-40 dark:border-fog/[0.1] dark:text-fog/70"
        >
          Previous
        </button>
        <span className="text-[10px] text-ink/40 dark:text-fog/40">
          {data ? `${Math.min(offset + 1, data.total)}–${Math.min(offset + PAGE, data.total)} of ${data.total}` : ""}
        </span>
        <button
          onClick={() => setOffset(offset + PAGE)}
          disabled={!data || offset + PAGE >= data.total || busy}
          className="rounded-lg border border-ink/[0.08] px-3 py-1.5 text-[11px] font-semibold text-ink/70 disabled:opacity-40 dark:border-fog/[0.1] dark:text-fog/70"
        >
          Next
        </button>
      </div>
    </section>
  );
}
