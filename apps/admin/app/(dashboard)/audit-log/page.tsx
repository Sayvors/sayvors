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

const METHODS = ["", "GET", "POST", "PUT", "PATCH", "DELETE"];

function statusStyle(code: number): string {
  if (code >= 200 && code < 300) return "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200";
  if (code >= 300 && code < 400) return "bg-sky-50 text-sky-700 ring-1 ring-sky-200";
  if (code >= 400 && code < 500) return "bg-amber-50 text-amber-700 ring-1 ring-amber-200";
  return "bg-red-50 text-red-700 ring-1 ring-red-200";
}

function methodStyle(method: string): string {
  switch (method.toUpperCase()) {
    case "GET":
      return "bg-sky-50 text-sky-700";
    case "POST":
      return "bg-emerald-50 text-emerald-700";
    case "PUT":
    case "PATCH":
      return "bg-amber-50 text-amber-700";
    case "DELETE":
      return "bg-red-50 text-red-700";
    default:
      return "bg-[var(--ui-surface)] text-[var(--ui-ink-2)]";
  }
}

export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);
  const [q, setQ] = useState("");
  const [method, setMethod] = useState("");
  const [status, setStatus] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      if (q.trim()) params.set("q", q.trim());
      if (method) params.set("method", method);
      if (status.trim()) params.set("status", status.trim());
      const data = await adminFetch<AuditEntry[]>(`/api/v1/admin/audit-log?${params.toString()}`);
      setEntries(data ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit log.");
    } finally {
      setLoading(false);
    }
  }, [limit, offset, q, method, status]);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const resetFilters = () => {
    setQ("");
    setMethod("");
    setStatus("");
    setOffset(0);
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Audit Log</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">Every action performed in the admin console. Click a row to expand full details.</p>
        </div>
      </div>

      {/* Search + filters */}
      <div className="panel flex flex-wrap items-center gap-2 p-3">
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setOffset(0); }}
          placeholder="Search action, path, operator, IP…"
          aria-label="Search audit log"
          className="input-field min-w-[220px] flex-1"
        />
        <select
          value={method}
          onChange={(e) => { setMethod(e.target.value); setOffset(0); }}
          aria-label="Filter by method"
          className="input-field w-auto"
        >
          {METHODS.map((m) => (
            <option key={m || "all"} value={m}>{m || "All methods"}</option>
          ))}
        </select>
        <input
          value={status}
          onChange={(e) => { setStatus(e.target.value.replace(/[^0-9]/g, "").slice(0, 3)); setOffset(0); }}
          placeholder="Status (e.g. 404)"
          aria-label="Filter by status code"
          inputMode="numeric"
          className="input-field w-32"
        />
        <button
          onClick={resetFilters}
          className="rounded-[2px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-medium text-ink/70 hover:bg-[var(--ui-sunken)]"
        >
          Reset
        </button>
      </div>

      {error && (
        <p role="alert" className="rounded-[2px] bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>
      )}

      <div className="panel overflow-hidden">
        <ul className="divide-y divide-[var(--ui-line)]">
          {loading ? (
            <li className="px-4 py-8 text-center text-[12px] text-ink/40">Loading…</li>
          ) : entries.length === 0 ? (
            <li className="px-4 py-8 text-center text-[12px] text-ink/40">No audit entries match.</li>
          ) : (
            entries.map((e) => {
              const open = expanded.has(e.id);
              return (
                <li key={e.id} className="transition-colors hover:bg-[var(--ui-sunken)]/40">
                  <button
                    onClick={() => toggle(e.id)}
                    aria-expanded={open}
                    className="flex w-full items-center gap-3 px-4 py-3 text-left"
                  >
                    <span className={`shrink-0 rounded-[2px] px-2 py-0.5 text-[10px] font-bold ${methodStyle(e.method)}`}>
                      {e.method}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[12px] text-ink">
                      <span className="font-semibold">{e.operator_username ?? "system"}</span>
                      <span className="mx-1.5 text-ink/30">·</span>
                      <span className="text-ink/70">{e.action}</span>
                      <span className="mx-1.5 text-ink/30">·</span>
                      <span className="font-mono text-[11px] text-ink/50">{e.path}</span>
                    </span>
                    <span className={`shrink-0 rounded-[2px] px-2 py-0.5 text-[10px] font-semibold ${statusStyle(e.status_code)}`}>
                      {e.status_code}
                    </span>
                    <span className="shrink-0 text-[10px] text-ink/40">{new Date(e.created_at).toLocaleTimeString()}</span>
                    <svg
                      aria-hidden
                      viewBox="0 0 12 12"
                      className={`h-3 w-3 shrink-0 text-ink/30 transition-transform ${open ? "rotate-180" : ""}`}
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                    >
                      <path d="M2 4l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>
                  {open && (
                    <div className="border-t border-[var(--ui-line)] bg-[var(--ui-sunken)]/30 px-4 py-3">
                      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
                        <Detail label="Time" value={new Date(e.created_at).toLocaleString()} />
                        <Detail label="Operator" value={e.operator_username ?? "system"} />
                        <Detail label="Operator ID" value={e.operator_id ?? "—"} mono />
                        <Detail label="Action" value={e.action} />
                        <Detail label="Method" value={e.method} />
                        <Detail label="Path" value={e.path} mono />
                        <Detail label="Status" value={String(e.status_code)} />
                        <Detail label="IP address" value={e.ip ?? "—"} mono />
                        <Detail label="Entry ID" value={e.id} mono />
                      </dl>
                    </div>
                  )}
                </li>
              );
            })
          )}
        </ul>
      </div>

      <div className="flex items-center justify-between">
        <button
          onClick={() => setOffset(Math.max(0, offset - limit))}
          disabled={offset === 0}
          className="rounded-[2px] border border-[var(--ui-line)] px-3 py-1.5 text-[12px] font-medium text-ink/70 disabled:opacity-40"
        >
          Previous
        </button>
        <span className="text-[11px] text-ink/40">Offset {offset} · showing {entries.length}</span>
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

function Detail({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="text-[10px] font-bold uppercase tracking-wide text-ink/40">{label}</dt>
      <dd className={`mt-0.5 break-all text-[12px] text-ink ${mono ? "font-mono text-[11px]" : ""}`}>{value}</dd>
    </div>
  );
}
