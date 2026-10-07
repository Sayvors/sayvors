"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";

/* Team management — members, roles and per-channel access. */

interface TeamRoleOption { id: string; name: string; is_system?: boolean; permissions?: string[] }
interface TeamChannelOption { id: string; platform: string; name?: string | null; status?: string }
interface TeamMemberRow {
  id: string | null;
  email: string;
  name?: string;
  role_name?: string;
  role_id?: string | null;
  is_owner?: boolean;
  status?: string;
  invited_at?: string | null;
  accepted_at?: string | null;
}
interface TeamContextInfo { business_name?: string | null; role_name?: string; is_owner?: boolean; permissions?: string[] }
interface CatalogArea {
  area: string;
  label: string;
  actions: { permission: string; action: string; label: string }[];
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function errText(e: unknown): string {
  if (e instanceof Error) {
    try {
      const parsed = JSON.parse(e.message);
      const d = parsed.detail;
      if (typeof d === "string") return d;
      if (d && typeof d === "object" && typeof d.message === "string") return d.message;
    } catch {
      /* not JSON — fall through */
    }
    return e.message;
  }
  return "Request failed";
}

function StatusBadge({ status }: { status?: string }) {
  const s = (status || "active").toLowerCase();
  const cls =
    s === "active"
      ? "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400"
      : s === "invited"
        ? "bg-amber-500/10 text-amber-600 dark:text-amber-400"
        : s === "suspended"
          ? "bg-red-500/10 text-red-600 dark:text-red-400"
          : "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.06] dark:text-fog/50";
  const label = s === "invited" ? "Invite pending" : s.charAt(0).toUpperCase() + s.slice(1);
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${cls}`}>{label}</span>;
}

function RoleBadge({ name, isOwner }: { name?: string; isOwner?: boolean }) {
  if (isOwner || name === "Owner") {
    return <span className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-semibold text-deep-violet">Owner</span>;
  }
  return <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-medium text-ink/60 dark:bg-fog/[0.06] dark:text-fog/60">{name || "No role"}</span>;
}

function Initial({ label, owner }: { label: string; owner?: boolean }) {
  return (
    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-bold ${owner ? "bg-deep-violet text-white" : "bg-ink/[0.07] text-ink/60 dark:bg-fog/[0.08] dark:text-fog/70"}`}>
      {(label || "?").trim().charAt(0).toUpperCase()}
    </div>
  );
}

function InviteForm({ roles, members, onInvited }: {
  roles: TeamRoleOption[];
  members: TeamMemberRow[];
  onInvited: () => void;
}) {
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [channelLevels, setChannelLevels] = useState<Record<string, string>>({});
  const [channels, setChannels] = useState<TeamChannelOption[]>([]);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const data = await apiFetch("/api/v1/team/channels");
        setChannels(data.channels || []);
      } catch {
        setChannels([]);
      }
    })();
  }, []);

  const normalized = email.trim().toLowerCase();
  const emailValid = EMAIL_RE.test(normalized);
  const duplicate = normalized ? members.find((m) => m.email.toLowerCase() === normalized) : undefined;
  const canSend = emailValid && !!roleId && !duplicate && !sending;

  const handleSubmit = async () => {
    setSending(true); setError(""); setSuccess("");
    try {
      const data = await apiFetch("/api/v1/team/invites", {
        method: "POST",
        body: JSON.stringify({ email: normalized, role_id: roleId, channel_levels: channelLevels }),
      });
      setSuccess(`Invite sent to ${data.email || normalized}.`);
      setEmail(""); setRoleId(""); setChannelLevels({});
      onInvited();
    } catch (e) {
      setError(errText(e));
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mt-3 space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="text-[11px] font-medium text-ink/60 dark:text-fog/60">Email</label>
          <input
            value={email}
            onChange={(e) => { setEmail(e.target.value); setError(""); setSuccess(""); }}
            placeholder="team-member@example.com"
            className="mt-1 w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog"
          />
          {email && !emailValid && (
            <p className="mt-1 text-[11px] text-red-600">Enter a valid email address.</p>
          )}
          {duplicate && (
            <p className="mt-1 text-[11px] text-amber-600 dark:text-amber-400">
              {duplicate.is_owner || duplicate.status === "active"
                ? "This person is already in the workspace."
                : "This person already has a pending invite — use Resend in the members list."}
            </p>
          )}
        </div>
        <div>
          <label className="text-[11px] font-medium text-ink/60 dark:text-fog/60">Role</label>
          <select
            value={roleId}
            onChange={(e) => { setRoleId(e.target.value); setError(""); setSuccess(""); }}
            className="mt-1 w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog"
          >
            <option value="">Select a role</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.name}{r.is_system ? " (built-in)" : ""}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="rounded-lg bg-ink/[0.03] p-3 dark:bg-fog/[0.04]">
        <p className="mb-2 text-[11px] font-semibold text-ink/60 dark:text-fog/60">Per-channel access (optional)</p>
        {channels.length === 0 ? (
          <p className="text-[11px] text-ink/40 dark:text-fog/40">No channels found for this workspace.</p>
        ) : (
          <div className="space-y-2">
            {channels.map((ch) => (
              <div key={ch.id} className="flex items-center justify-between gap-2 rounded-md bg-white/40 px-2 py-1.5 dark:bg-ink/20">
                <span className="truncate text-[11px] text-ink/70 dark:text-fog/70">{ch.name || ch.platform}</span>
                <select
                  value={channelLevels[ch.id] || ""}
                  onChange={(e) => setChannelLevels({ ...channelLevels, [ch.id]: e.target.value })}
                  className="rounded-md border border-ink/10 bg-white px-1.5 py-0.5 text-[10px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog"
                >
                  <option value="">none</option>
                  <option value="view">view</option>
                  <option value="edit">edit</option>
                </select>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={!canSend}
          className="rounded-lg bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-40"
        >
          {sending ? "Sending…" : "Send invite"}
        </button>
        {success && <p className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">{success}</p>}
        {error && <p className="text-[11px] text-red-600">{error}</p>}
      </div>
    </div>
  );
}

function RoleBuilder({ onCreated }: { onCreated: () => void }) {
  const [areas, setAreas] = useState<CatalogArea[]>([]);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [openAreas, setOpenAreas] = useState<Record<string, boolean>>({});
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const data = await apiFetch("/api/v1/team/permissions");
        setAreas(data.areas || []);
      } catch {
        setAreas([]);
      }
    })();
  }, []);

  const selectedSet = new Set(selected);
  const q = query.trim().toLowerCase();
  const visibleAreas = areas
    .map((a) => ({
      ...a,
      actions: q
        ? a.actions.filter(
            (act) =>
              act.label.toLowerCase().includes(q) ||
              act.permission.toLowerCase().includes(q) ||
              a.label.toLowerCase().includes(q),
          )
        : a.actions,
    }))
    .filter((a) => a.actions.length > 0);

  const toggle = (perm: string) => {
    setSuccess(""); setError("");
    setSelected((prev) => (prev.includes(perm) ? prev.filter((p) => p !== perm) : [...prev, perm]));
  };

  const setArea = (area: CatalogArea, on: boolean) => {
    setSuccess(""); setError("");
    const perms = area.actions.map((a) => a.permission);
    setSelected((prev) =>
      on ? Array.from(new Set([...prev, ...perms])) : prev.filter((p) => !perms.includes(p)),
    );
  };

  const canCreate = name.trim().length > 0 && selected.length > 0 && !creating;

  const handleCreate = async () => {
    setCreating(true); setError(""); setSuccess("");
    try {
      const data = await apiFetch("/api/v1/team/roles", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), permissions: selected }),
      });
      setSuccess(`Role "${data.name}" created.`);
      setName(""); setSelected([]);
      onCreated();
    } catch (e) {
      setError(errText(e));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mt-3 space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="flex-1">
          <label className="text-[11px] font-medium text-ink/60 dark:text-fog/60">Role name</label>
          <input
            value={name}
            onChange={(e) => { setName(e.target.value); setError(""); setSuccess(""); }}
            placeholder="e.g. Shift lead"
            className="mt-1 w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog"
          />
        </div>
        <button
          onClick={handleCreate}
          disabled={!canCreate}
          className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-40"
        >
          {creating ? "Creating…" : `Create role${selected.length ? ` · ${selected.length} permission${selected.length === 1 ? "" : "s"}` : ""}`}
        </button>
      </div>
      {success && <p className="text-[11px] font-medium text-emerald-600 dark:text-emerald-400">{success}</p>}
      {error && <p className="text-[11px] text-red-600">{error}</p>}

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search permissions…"
        className="w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[12px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog"
      />

      {areas.length === 0 ? (
        <p className="text-[12px] text-ink/40 dark:text-fog/40">Could not load the permission catalog.</p>
      ) : visibleAreas.length === 0 ? (
        <p className="text-[12px] text-ink/40 dark:text-fog/40">No permissions match your search.</p>
      ) : (
        <div className="space-y-1.5">
          {visibleAreas.map((area) => {
            const count = area.actions.filter((a) => selectedSet.has(a.permission)).length;
            const open = q ? true : !!openAreas[area.area];
            return (
              <div key={area.area} className="overflow-hidden rounded-xl border border-ink/[0.06] dark:border-fog/[0.08]">
                <button
                  type="button"
                  onClick={() => { if (!q) setOpenAreas((prev) => ({ ...prev, [area.area]: !prev[area.area] })); }}
                  aria-expanded={open}
                  className="flex w-full items-center gap-2 bg-ink/[0.02] px-3 py-2 text-left transition hover:bg-ink/[0.04] dark:bg-fog/[0.03] dark:hover:bg-fog/[0.05]"
                >
                  <svg
                    viewBox="0 0 12 12"
                    fill="none"
                    className={`h-3 w-3 shrink-0 text-ink/35 transition-transform dark:text-fog/35 ${open ? "rotate-90" : ""}`}
                  >
                    <path d="M4.5 2.5 8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span className="text-[12px] font-semibold text-ink/70 dark:text-fog/70">{area.label}</span>
                  {count > 0 && (
                    <span className="rounded-full bg-deep-violet/10 px-1.5 py-0.5 text-[10px] font-semibold text-deep-violet">{count}</span>
                  )}
                  <span className="ml-auto text-[10px] tabular-nums text-ink/35 dark:text-fog/35">{count}/{area.actions.length}</span>
                </button>
                {open && (
                  <div className="border-t border-ink/[0.04] p-1.5 dark:border-fog/[0.06]">
                    <div className="grid gap-0.5 sm:grid-cols-2">
                      {area.actions.map((act) => {
                        const on = selectedSet.has(act.permission);
                        return (
                          <label
                            key={act.permission}
                            className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.04]"
                          >
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={() => toggle(act.permission)}
                              className="h-3.5 w-3.5 accent-deep-violet"
                            />
                            <span className="text-[12px] font-medium text-ink/75 dark:text-fog/75">{act.label}</span>
                            <span className="ml-auto font-mono text-[10px] text-ink/30 dark:text-fog/30">{act.permission}</span>
                          </label>
                        );
                      })}
                    </div>
                    {!q && (
                      <div className="flex justify-end gap-3 px-2 pb-1 pt-1.5">
                        <button type="button" onClick={() => setArea(area, true)} className="text-[10px] font-semibold text-deep-violet hover:underline">
                          Select all
                        </button>
                        <button type="button" onClick={() => setArea(area, false)} className="text-[10px] font-semibold text-ink/40 hover:underline dark:text-fog/40">
                          Clear
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function TeamPage() {
  const [members, setMembers] = useState<TeamMemberRow[]>([]);
  const [roles, setRoles] = useState<TeamRoleOption[]>([]);
  const [context, setContext] = useState<TeamContextInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const loadMembers = useCallback(async () => {
    try {
      const data = await apiFetch("/api/v1/team/members");
      setMembers(data.members || []);
    } catch {
      setMembers([]);
    }
  }, []);

  const loadRoles = useCallback(async () => {
    try {
      const data = await apiFetch("/api/v1/team/roles");
      setRoles(data.roles || []);
    } catch {
      setRoles([]);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setContext(await apiFetch("/api/v1/team/context"));
      } catch {
        /* not authenticated — redirect handled by nav gating */
      }
      await Promise.all([loadMembers(), loadRoles()]);
      setLoading(false);
    })();
  }, [loadMembers, loadRoles]);

  const resendInvite = async (id: string) => {
    setNotice(null);
    try {
      await apiFetch(`/api/v1/team/invites/${id}/resend`, { method: "POST" });
      setNotice({ kind: "ok", text: "Invite email resent." });
      await loadMembers();
    } catch (e) {
      setNotice({ kind: "err", text: errText(e) });
    }
  };

  return (
    <div className="h-full overflow-y-auto p-4 pb-24 space-y-6 sm:p-6">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Team management</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
            Members, roles and per-channel access.
          </p>
        </div>
        {context && (
          <p className="text-[12px] text-ink/50 dark:text-fog/50">
            {context.business_name || "Your workspace"} · <span className="font-semibold text-deep-violet">{context.role_name || "Owner"}</span>
          </p>
        )}
      </div>

      {loading ? (
        <p className="text-[13px] text-ink/40 dark:text-fog/40">Loading…</p>
      ) : (
        <div className="space-y-6">
          {/* Members */}
          <section className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm dark:border-fog/10 dark:bg-ink">
            <div className="flex items-center justify-between">
              <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Members</h2>
              <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[10px] font-semibold text-ink/50 dark:bg-fog/[0.06] dark:text-fog/50">
                {members.length}
              </span>
            </div>
            <div className="mt-3 space-y-2">
              {members.length === 0 ? (
                <p className="text-[13px] text-ink/35 dark:text-fog/35">No members yet.</p>
              ) : (
                members.map((m) => (
                  <div
                    key={m.id || m.email}
                    className="flex items-center justify-between gap-3 rounded-xl border border-ink/[0.05] bg-ink/[0.02] px-3 py-2.5 dark:border-fog/[0.06] dark:bg-fog/[0.03]"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <Initial label={m.name || m.email} owner={m.is_owner} />
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-semibold text-ink dark:text-fog">{m.email}</p>
                        <div className="mt-0.5 flex items-center gap-1.5">
                          <RoleBadge name={m.role_name} isOwner={m.is_owner} />
                          <StatusBadge status={m.status} />
                        </div>
                      </div>
                    </div>
                    {m.status === "invited" && m.id && (
                      <button
                        onClick={() => resendInvite(m.id as string)}
                        className="shrink-0 rounded-lg border border-ink/10 px-2.5 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:border-deep-violet/30 hover:text-deep-violet dark:border-fog/10 dark:text-fog/60"
                      >
                        Resend
                      </button>
                    )}
                  </div>
                ))
              )}
            </div>
            {notice && (
              <p className={`mt-2 text-[11px] ${notice.kind === "ok" ? "font-medium text-emerald-600 dark:text-emerald-400" : "text-red-600"}`}>
                {notice.text}
              </p>
            )}
          </section>

          {/* Roles */}
          <section className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm dark:border-fog/10 dark:bg-ink">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Roles</h2>
            <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">
              Built-in roles (Admin, Agent, Viewer) are read-only — create custom roles with the Role builder below.
            </p>
            <div className="mt-3 space-y-2">
              {roles.length === 0 ? (
                <p className="text-[13px] text-ink/35 dark:text-fog/35">No roles yet.</p>
              ) : (
                roles.map((r) => {
                  const perms = Array.from(new Set(r.permissions || []));
                  return (
                    <div key={r.id} className="rounded-xl border border-ink/[0.05] bg-ink/[0.02] px-3 py-2.5 dark:border-fog/[0.06] dark:bg-fog/[0.03]">
                      <div className="flex items-center gap-2">
                        <p className="text-[13px] font-semibold text-ink dark:text-fog">{r.name}</p>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${r.is_system ? "bg-deep-violet/10 text-deep-violet" : "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.06] dark:text-fog/50"}`}>
                          {r.is_system ? "Built-in" : "Custom"}
                        </span>
                        <span className="ml-auto text-[11px] text-ink/40 dark:text-fog/40">
                          {perms.length} permission{perms.length === 1 ? "" : "s"}
                        </span>
                      </div>
                      <details className="mt-1.5">
                        <summary className="cursor-pointer text-[11px] text-ink/45 dark:text-fog/45">View permissions</summary>
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {perms.map((p) => (
                            <span key={p} className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] text-ink/55 dark:bg-fog/[0.06] dark:text-fog/55">{p}</span>
                          ))}
                        </div>
                      </details>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {/* Invite member */}
          <section className="rounded-2xl border border-deep-violet/10 bg-deep-violet/[0.03] p-5 dark:border-deep-violet/20 dark:bg-deep-violet/[0.06]">
            <h2 className="text-[15px] font-semibold text-deep-violet">Invite member</h2>
            <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">
              The recipient gets an email with a link to set up their access. Pending invites can be resent from the members list.
            </p>
            <InviteForm roles={roles} members={members} onInvited={loadMembers} />
          </section>

          {/* Role builder */}
          <section className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm dark:border-fog/10 dark:bg-ink">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Role builder</h2>
            <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">
              Pick permissions and give the role a name. New roles appear in the list above and in the invite form.
            </p>
            <RoleBuilder onCreated={loadRoles} />
          </section>
        </div>
      )}
    </div>
  );
}
