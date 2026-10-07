"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

/* Team RBAC Phase 1 — frontend skeleton */

function InviteFormSkeleton() {
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [channelLevels, setChannelLevels] = useState<Record<string, string>>({});
  const [channels, setChannels] = useState<any[]>([]);
  const [sending, setSending] = useState(false);
  const [sentMsg, setSentMsg] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/v1/team/channels", { credentials: "include" });
        if (res.ok) {
          const data = await res.json();
          setChannels(data.channels || []);
        }
      } catch {
        setChannels([]);
      }
    })();
  }, []);

  const handleSubmit = async () => {
    setSending(true); setSentMsg("");
    try {
      const res = await fetch("/api/v1/team/invites", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email, role_id: roleId, channel_levels: channelLevels }),
      });
      const data = await res.json();
      if (res.ok) {
        setSentMsg("Invite sent. Email: " + (data.email || email));
        setEmail(""); setRoleId(""); setChannelLevels({});
      } else {
        setSentMsg(data.detail || "Invite failed.");
      }
    } catch {
      setSentMsg("Network error — invite not sent.");
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="mt-3 space-y-3 rounded-lg bg-white/60 p-3 dark:bg-ink/30">
      <div>
        <label className="text-[11px] font-medium text-ink/60 dark:text-fog/60">Email</label>
        <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="team-member@example.com" className="mt-1 w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog" />
      </div>
      <div>
        <label className="text-[11px] font-medium text-ink/60 dark:text-fog/60">Role</label>
        <select value={roleId} onChange={(e) => setRoleId(e.target.value)} className="mt-1 w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog">
          <option value="">Select a role</option>
          <option value="admin">Admin</option>
          <option value="agent">Agent</option>
          <option value="viewer">Viewer</option>
        </select>
      </div>
      <div className="rounded-lg bg-ink/[0.03] p-3 dark:bg-fog/[0.04]">
        <p className="text-[11px] font-semibold text-ink/60 dark:text-fog/60 mb-2">Per-channel access (optional)</p>
        {channels.length === 0 ? (
          <p className="text-[11px] text-ink/40 dark:text-fog/40">No channels found for this workspace.</p>
        ) : (
          <div className="space-y-2">
            {channels.map((ch: any) => (
              <div key={ch.id || ch.platform} className="flex items-center justify-between rounded-md bg-white/40 dark:bg-ink/20 px-2 py-1.5">
                <span className="text-[11px] text-ink/70 dark:text-fog/70">{ch.name || ch.platform || ch.id}</span>
                <select
                  value={channelLevels[ch.id || ch.platform] || ""}
                  onChange={(e) => setChannelLevels({ ...channelLevels, [ch.id || ch.platform]: e.target.value })}
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
      <button onClick={handleSubmit} disabled={sending || !email || !roleId} className="rounded-lg bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white shadow-sm hover:bg-deep-violet/90 transition disabled:opacity-40">{sending ? "Sending…" : "Send invite"}</button>
      {sentMsg && <p className="text-[11px] text-ink/60 dark:text-fog/60">{sentMsg}</p>}
    </div>
  );
}

function RoleBuilderSkeleton() {
  const [selected, setSelected] = useState<string[]>([]);
  const [cloning, setCloning] = useState(false);
  const [cloneMsg, setCloneMsg] = useState("");
  const catalog = [
    { area: "inbox", actions: ["view","reply"] },
    { area: "channels", actions: ["view","edit","connect","remove"] },
    { area: "reviews", actions: ["view","reply"] },
    { area: "posts", actions: ["view","create"] },
    { area: "analytics", actions: ["view"] },
    { area: "media", actions: ["view","upload"] },
    { area: "ai", actions: ["view"] },
    { area: "team", actions: ["view","manage"] },
  ];
  const handleClone = async () => {
    if (selected.length === 0) { setCloneMsg("Select at least one permission."); return; }
    setCloning(true); setCloneMsg("");
    try {
      const res = await fetch("/api/v1/team/roles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: "Custom " + selected.slice(0, 2).join("+"), permissions: selected }),
      });
      const data = await res.json();
      if (res.ok) {
        setCloneMsg("Role created: " + (data.name || "new custom role"));
        setSelected([]);
      } else {
        setCloneMsg(data.detail || "Failed to create role.");
      }
    } catch {
      setCloneMsg("Network error — role not created.");
    } finally {
      setCloning(false);
    }
  };

  return (
    <div className="mt-3 space-y-2">
      <p className="text-[12px] text-ink/40 dark:text-fog/40">Select permissions from the catalog. System roles (Admin, Agent, Viewer) are read-only — clone to create a custom role.</p>
      <div className="flex flex-wrap gap-2">
        {catalog.flatMap((a) => a.actions.map((ac) => `${a.area}.${ac}`)).map((p) => (
          <button key={p} onClick={() => setSelected((prev) => prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p])} className={`rounded-full px-2.5 py-1 text-[10px] font-medium transition ${selected.includes(p) ? "bg-deep-violet/15 text-deep-violet" : "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.06] dark:text-fog/50"}`}>{p}</button>
        ))}
      </div>
      <button onClick={handleClone} disabled={cloning || selected.length === 0} className="mt-2 rounded-lg border border-deep-violet/20 px-3 py-1.5 text-[11px] font-semibold text-deep-violet hover:bg-deep-violet/[0.04] transition disabled:opacity-40">{cloning ? "Creating…" : "Clone selected to new role"}</button>
      {cloneMsg && <p className="text-[11px] text-ink/60 dark:text-fog/60">{cloneMsg}</p>}
    </div>
  );
}

export default function TeamPage() {
  const [members, setMembers] = useState<any[]>([]);
  const [roles, setRoles] = useState<any[]>([]);
  const [context, setContext] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const ctxRes = await fetch("/api/v1/team/context", { credentials: "include" });
        if (ctxRes.ok) setContext(await ctxRes.json());
      } catch {
        /* not authenticated — redirect handled by nav gating */
      }
      try {
        const memRes = await fetch("/api/v1/team/members", { credentials: "include" });
        if (memRes.ok) setMembers(await memRes.json());
      } catch { setMembers([]); }
      try {
        const roleRes = await fetch("/api/v1/team/roles", { credentials: "include" });
        if (roleRes.ok) setRoles(await roleRes.json());
      } catch { setRoles([]); }
      setLoading(false);
    })();
  }, []);

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div>
        <h1 className="text-[20px] font-bold text-ink dark:text-fog">Team management</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
          Members, roles and per-channel access.
        </p>
      </div>

      {loading ? (
        <p className="text-[13px] text-ink/40 dark:text-fog/40">Loading…</p>
      ) : (
        <div className="space-y-6">
          {/* Members tab */}
          <section className="rounded-2xl border border-ink/10 bg-white dark:border-fog/10 dark:bg-ink p-5 shadow-sm">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Members</h2>
            <p className="text-[11px] text-ink/40 dark:text-fog/40 mt-0.5">Guideline: Members are people invited or added to this workspace. Each entry shows the assigned role and status. Owners manage membership and can modify roles.</p>
            <div className="mt-3 space-y-2">
              {members.length === 0 ? (
                <p className="text-[13px] text-ink/35 dark:text-fog/35">No members yet.</p>
              ) : (
                members.map((m: any) => (
                  <div key={m.id} className="flex items-center justify-between rounded-lg border border-ink/[0.05] bg-ink/[0.02] px-3 py-2.5 dark:border-fog/[0.06] dark:bg-fog/[0.03]">
                    <div>
                      <p className="text-[13px] font-semibold text-ink dark:text-fog">{m.email}</p>
                      <p className="text-[11px] text-ink/40 dark:text-fog/40">Role: {m.role_name || "—"} · Status: {m.status}</p>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>

          {/* Roles tab */}
          <section className="rounded-2xl border border-ink/10 bg-white dark:border-fog/10 dark:bg-ink p-5 shadow-sm">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Roles</h2>
            <p className="text-[11px] text-ink/40 dark:text-fog/40 mt-0.5">Guideline: Roles define permission sets. System roles (Admin, Agent, Viewer) are built-in; clone them only via the Role builder below to create custom roles.</p>
            <div className="mt-3 space-y-2">
              {roles.length === 0 ? (
                <p className="text-[13px] text-ink/35 dark:text-fog/35">No roles yet.</p>
              ) : (
                roles.map((r: any) => (
                  <div key={r.id} className="rounded-lg border border-ink/[0.05] bg-ink/[0.02] px-3 py-2.5 dark:border-fog/[0.06] dark:bg-fog/[0.03]">
                    <p className="text-[13px] font-semibold text-ink dark:text-fog">{r.name}</p>
                    <p className="text-[11px] text-ink/40 dark:text-fog/40">Permissions: {(r.permissions || []).join(", ") || "—"}</p>
                  </div>
                ))
              )}
            </div>
          </section>

          {/* Invite modal (functional skeleton) */}
          <section className="rounded-2xl border border-deep-violet/10 bg-deep-violet/[0.03] p-5 dark:border-deep-violet/20 dark:bg-deep-violet/[0.06]">
            <h2 className="text-[15px] font-semibold text-deep-violet">Invite member</h2>
            <p className="text-[11px] text-ink/40 dark:text-fog/40 mt-0.5">Guideline: Send an invite by providing an email, selecting a role, and optionally setting per-channel access. The recipient receives an email with an invite link.</p>
            <InviteFormSkeleton />
          </section>

          {/* Role builder (functional skeleton) */}
          <section className="rounded-2xl border border-ink/10 bg-white dark:border-fog/10 dark:bg-ink p-5 shadow-sm">
            <h2 className="text-[15px] font-semibold text-ink dark:text-fog">Role builder</h2>
            <p className="text-[11px] text-ink/40 dark:text-fog/40 mt-0.5">Guideline: Select permissions from the catalog to build a custom role. Click "Clone selected to new role" to save it; the new role appears in the Roles list above.</p>
            <RoleBuilderSkeleton />
          </section>

          {/* Context / nav gating info */}
          {context && (
            <section className="rounded-2xl border border-deep-violet/10 bg-deep-violet/[0.03] p-4 dark:border-deep-violet/20 dark:bg-deep-violet/[0.06]">
              <h3 className="text-[14px] font-semibold text-deep-violet">Workspace context</h3>
              <p className="text-[12px] text-ink/60 dark:text-fog/60 mt-1">Tenant: {context.tenant_id} · Role: {context.role_name || "—"}</p>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
