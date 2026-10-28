"use client";

import { useCallback, useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";

interface Operator {
  id: string;
  username: string;
  role: string;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export default function OperatorsPage() {
  const [operators, setOperators] = useState<Operator[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("operator");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await adminFetch<Operator[]>("/api/v1/admin/operators");
      setOperators(data ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load operators.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) return;
    setBusy(true);
    setError(null);
    try {
      await adminFetch("/api/v1/admin/operators", {
        method: "POST",
        body: JSON.stringify({ username, password, role }),
      });
      setUsername("");
      setPassword("");
      setRole("operator");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create operator.");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (op: Operator) => {
    try {
      await adminFetch(`/api/v1/admin/operators/${op.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !op.is_active }),
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update operator.");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[20px] font-bold text-ink">Operators</h1>
        <p className="mt-0.5 text-[12px] text-ink/50">Named accounts with access to this admin console.</p>
      </div>

      <form onSubmit={create} className="panel space-y-3 p-4">
        <p className="text-[12px] font-semibold text-ink">Add operator</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <input className="input-field" placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input className="input-field" type="password" placeholder="Password (min 8)" value={password} onChange={(e) => setPassword(e.target.value)} />
          <select className="input-field" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="operator">Operator</option>
            <option value="superadmin">Superadmin</option>
          </select>
        </div>
        <button type="submit" disabled={busy || !username || !password} className="btn-primary px-4 py-2 text-[12px] font-semibold disabled:opacity-50">
          {busy ? "Creating…" : "Create operator"}
        </button>
      </form>

      {error && (
        <p role="alert" className="rounded-[2px] bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-[var(--ui-line)] text-left text-[11px] font-semibold uppercase tracking-wide text-ink/50">
              <th className="px-3 py-2">Username</th>
              <th className="px-3 py-2">Role</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Last login</th>
              <th className="px-3 py-2">Created</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-ink/40">Loading…</td></tr>
            ) : operators.length === 0 ? (
              <tr><td colSpan={6} className="px-3 py-6 text-center text-ink/40">No operators yet.</td></tr>
            ) : (
              operators.map((op) => (
                <tr key={op.id} className="border-b border-[var(--ui-line)] last:border-0">
                  <td className="px-3 py-2 font-medium text-ink">{op.username}</td>
                  <td className="px-3 py-2 text-ink/70">{op.role}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-[2px] px-2 py-0.5 text-[10px] font-semibold ${op.is_active ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
                      {op.is_active ? "active" : "disabled"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-ink/60">{op.last_login_at ? new Date(op.last_login_at).toLocaleString() : "—"}</td>
                  <td className="px-3 py-2 text-ink/60">{new Date(op.created_at).toLocaleString()}</td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() => toggle(op)}
                      className="rounded-[2px] border border-[var(--ui-line)] px-2 py-1 text-[11px] font-medium text-ink/70 hover:border-[var(--ui-ink)] hover:text-ink"
                    >
                      {op.is_active ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
