"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

interface AuditEntry {
  id: string;
  operator_id: string | null;
  operator_username: string | null;
  action: string;
  method: string;
  path: string;
  status_code: number;
  ip: string | null;
  created_at: string;
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit] = useState(100);
  const [offset, setOffset] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await adminFetch<AuditEntry[]>(`/api/v1/admin/audit-log?limit=${limit}&offset=${offset}`);
      setEntries(data ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit log.");
    } finally {
      setLoading(false);
    }
  }, [limit, offset]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[20px] font-bold text-ink">Audit Log</h1>
        <p className="mt-0.5 text-[12px] text-ink/50">Every action performed in the admin console.</p>
      </div>

      {error && (
        <p role="alert" className="rounded-[2px] bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-[var(--ui-line)] text-left text-[11px] font-semibold uppercase tracking-wide text-ink/50">
              <th className="px-3 py-2">Time</th>
              <th className="px-3 py-2">Operator</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Method</th>
              <th className="px-3 py-2">Path</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">IP</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-ink/40">Loading…</td></tr>
            ) : entries.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-ink/40">No audit entries yet.</td></tr>
            ) : (
              entries.map((e) => (
                <tr key={e.id} className="border-b border-[var(--ui-line)] last:border-0">
                  <td className="px-3 py-2 text-ink/60">{new Date(e.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2 font-medium text-ink">{e.operator_username ?? "—"}</td>
                  <td className="px-3 py-2 text-ink/70">{e.action}</td>
                  <td className="px-3 py-2 text-ink/60">{e.method}</td>
                  <td className="px-3 py-2 text-ink/60 font-mono text-[11px]">{e.path}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-[2px] px-2 py-0.5 text-[10px] font-semibold ${e.status_code < 400 ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
                      {e.status_code}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-ink/60">{e.ip ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <button
          onClick={() => setOffset(Math.max(0, offset - limit))}
          disabled={offset === 0}
          className="rounded-[2px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-medium text-ink/70 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-[11px] text-ink/40">Offset {offset}</span>
        <button
          onClick={() => setOffset(offset + limit)}
          disabled={entries.length < limit}
          className="rounded-[2px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-medium text-ink/70 disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
