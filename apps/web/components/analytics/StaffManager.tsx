"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api-rag";

/* Employee registry for the Team page (§33): owner-managed, per branch,
 * no login. Reads ?addName= when the Analytics unassigned-names panel sends
 * the owner here to register a name they found in a review. */

interface Employee {
  id: string;
  listing_id: string;
  name: string;
  aliases: string[];
  active: boolean;
}

interface ChannelRow {
  id: string;
  platform: string;
  listing_id?: string | null;
  display_name?: string | null;
}

export default function StaffManager() {
  const params = useSearchParams();
  const addName = params.get("addName") ?? "";

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [branches, setBranches] = useState<{ id: string; name: string }[]>([]);
  const [name, setName] = useState(addName);
  const [aliases, setAliases] = useState("");
  const [listingId, setListingId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [emp, chans] = await Promise.all([
        apiFetch("/api/v1/staff"),
        apiFetch("/api/v1/channels?limit=100"),
      ]);
      setEmployees(emp.employees ?? []);
      const google = (chans.channels ?? []).filter(
        (c: ChannelRow) => c.platform === "google_reviews",
      );
      const opts = google.map((c: ChannelRow) => ({
        id: c.listing_id ?? c.id,
        name: c.display_name ?? "Branch",
      }));
      setBranches(opts);
      setListingId((prev) => prev || opts[0]?.id || "");
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Could not load employees.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async () => {
    if (!name.trim() || !listingId) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await apiFetch("/api/v1/staff", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          listing_id: listingId,
          aliases: aliases.split(",").map((a) => a.trim()).filter(Boolean),
        }),
      });
      setNotice(`${name.trim()} added. Their mentions will link automatically from now on.`);
      setName("");
      setAliases("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Could not add the employee.");
    } finally {
      setBusy(false);
    }
  };

  const toggleActive = async (emp: Employee) => {
    setError(null);
    try {
      await apiFetch(`/api/v1/staff/${emp.id}`, {
        method: "PATCH",
        body: JSON.stringify({ active: !emp.active }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Update failed.");
    }
  };

  const remove = async (emp: Employee) => {
    setError(null);
    try {
      await apiFetch(`/api/v1/staff/${emp.id}`, { method: "DELETE" });
      setNotice(`${emp.name} removed. Their past mentions stay in your analytics as unassigned names.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Delete failed.");
    }
  };

  const branchName = (listingId_: string) =>
    branches.find((b) => b.id === listingId_)?.name ?? listingId_;

  return (
    <div className="space-y-4">
      {notice && (
        <p role="status" className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] px-3 py-2 text-[12px] font-medium text-[var(--ui-ink)]">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="rounded-[10px] border border-red-500/40 bg-red-500/10 px-3 py-2 text-[12px] font-medium text-red-700 dark:text-red-400">
          {error}
        </p>
      )}

      <div className="rounded-[10px] border border-[var(--ui-line)] p-4">
        <h3 className="text-[13px] font-bold text-[var(--ui-ink)]">
          {addName ? `Add "${addName}" as an employee` : "Add an employee"}
        </h3>
        <p className="mt-0.5 text-[11.5px] text-[var(--ui-ink-2)]">
          Reviews that mention this name are counted for them. Aliases are other spellings customers might use.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (e.g. Ahmad)"
            aria-label="Employee name"
            className="rounded-[10px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)] outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          />
          <select
            value={listingId}
            onChange={(e) => setListingId(e.target.value)}
            aria-label="Branch"
            className="rounded-[10px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-2 text-[13px] text-[var(--ui-ink)]"
          >
            {branches.length === 0 && <option value="">No branches connected</option>}
            {branches.map((b) => (
              <option key={b.id} value={b.id}>{b.name}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={add}
            disabled={busy || !name.trim() || !listingId}
            className="rounded-[10px] bg-[var(--ui-ink)] px-4 py-2 text-[13px] font-bold text-[var(--ui-on-ink)] transition hover:opacity-90 disabled:opacity-50"
          >
            {busy ? "Adding…" : "Add"}
          </button>
        </div>
        <input
          value={aliases}
          onChange={(e) => setAliases(e.target.value)}
          placeholder="Aliases, comma-separated (e.g. Ahmed, Ahmad Ali)"
          aria-label="Name aliases"
          className="mt-2 w-full rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] text-[var(--ui-ink)] outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        />
      </div>

      {loading ? (
        <p className="py-6 text-center text-[13px] text-[var(--ui-ink-2)]">Loading employees…</p>
      ) : employees.length === 0 ? (
        <p className="rounded-[10px] border border-dashed border-[var(--ui-line)] px-4 py-8 text-center text-[13px] text-[var(--ui-ink-2)]">
          No employees yet. Add your first one above — reviews naming them will count toward their record.
        </p>
      ) : (
        <ul className="space-y-2">
          {employees.map((emp) => (
            <li key={emp.id} className="flex flex-wrap items-center gap-2 rounded-[10px] border border-[var(--ui-line)] px-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-bold text-[var(--ui-ink)]">
                  {emp.name}
                  {!emp.active && (
                    <span className="ml-2 rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold uppercase text-[var(--ui-ink-2)]">Inactive</span>
                  )}
                </p>
                <p className="truncate text-[11px] text-[var(--ui-ink-2)]">
                  {branchName(emp.listing_id)}
                  {emp.aliases.length > 0 ? ` · also: ${emp.aliases.join(", ")}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => toggleActive(emp)}
                className="rounded-[10px] border border-[var(--ui-line-strong)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)]"
              >
                {emp.active ? "Deactivate" : "Activate"}
              </button>
              <button
                type="button"
                onClick={() => remove(emp)}
                className="rounded-[10px] border border-red-300 px-3 py-1.5 text-[12px] font-semibold text-red-600 transition hover:bg-red-50 dark:hover:bg-red-500/10"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
