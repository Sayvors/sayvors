"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";

/* Invite /join page — phase 1 skeleton */

export default function InvitePage() {
  return (
    <Suspense fallback={<div className="p-6 text-[13px] text-ink/40">Loading invite…</div>}>
      <InviteContent />
    </Suspense>
  );
}

function InviteContent() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params?.get("token") ?? "";
  const [preview, setPreview] = useState<any | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [mode, setMode] = useState<"preview" | "new" | "existing" | "done">("preview");
  const [acceptMsg, setAcceptMsg] = useState("");

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const res = await fetch(`/api/v1/team/invites/preview?token=${encodeURIComponent(token)}`, { credentials: "include" });
        if (res.ok) {
          const data = await res.json();
          setPreview(data);
          setEmail(data.email || "");
        } else {
          setMode("existing");
        }
      } catch {
        setMode("existing");
      }
    })();
  }, [token]);

  if (!token) {
    return <div className="p-6 text-[13px] text-red-600">Invalid or missing invite token.</div>;
  }

  return (
    <div className="mx-auto max-w-md p-6 space-y-6">
      <h1 className="text-[20px] font-bold text-ink dark:text-fog">Team invite</h1>
      {mode === "preview" && (
        <div className="rounded-2xl border border-ink/10 bg-white p-5 dark:border-fog/10 dark:bg-ink shadow-sm space-y-3">
          <p className="text-[13px] text-ink/70 dark:text-fog/70">You were invited by <strong>{preview?.invited_by_email || "a workspace owner"}</strong>.</p>
          <p className="text-[12px] text-ink/40 dark:text-fog/40">Role: <span className="font-semibold text-ink/70 dark:text-fog/70">{preview?.role || "—"}</span></p>
          {preview?.channel_levels && Object.keys(preview.channel_levels).length > 0 && (
            <div className="rounded-lg bg-ink/[0.03] p-3 text-[12px] dark:bg-fog/[0.04]">
              <p className="font-semibold text-ink/60 dark:text-fog/60 mb-1">Channel access</p>
              {Object.entries(preview.channel_levels as Record<string, string>).map(([ch, lvl]) => (
                <p key={ch} className="text-ink/50 dark:text-fog/50">{ch}: <span className="font-medium">{lvl}</span></p>
              ))}
            </div>
          )}
          <button
            onClick={() => setMode("new")}
            className="mt-2 w-full rounded-lg bg-deep-violet px-4 py-2.5 text-[13px] font-semibold text-white shadow-sm hover:bg-deep-violet/90 transition"
          >
            Accept invite
          </button>
        </div>
      )}
      {mode === "new" && (
        <div className="rounded-2xl border border-ink/10 bg-white p-5 dark:border-fog/10 dark:bg-ink shadow-sm space-y-4">
          <p className="text-[14px] font-semibold text-ink dark:text-fog">Create your account</p>
          <div className="space-y-2">
            <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Email</label>
            <input value={email} readOnly className="w-full rounded-lg border border-ink/10 bg-ink/[0.04] px-3 py-2 text-[13px] text-ink/50 dark:border-fog/10 dark:bg-fog/[0.04] dark:text-fog/50" />
          </div>
          <div className="space-y-2">
            <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Password</label>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Set a password" className="w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.08] dark:border-fog/10 dark:bg-ink dark:text-fog" />
          </div>
          <button
            onClick={async () => {
              try {
                const res = await fetch("/api/v1/team/invites/accept", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  credentials: "include",
                  body: JSON.stringify({ token, password }),
                });
                const data = await res.json();
                if (res.ok) {
                  setMode("done");
                } else if (data.detail?.code === "login_required") {
                  setMode("existing");
                } else {
                  setAcceptMsg(data.detail || JSON.stringify(data));
                }
              } catch {
                setAcceptMsg("Network error — could not accept invite.");
              }
            }}
            className="w-full rounded-lg bg-deep-violet px-4 py-2.5 text-[13px] font-semibold text-white shadow-sm hover:bg-deep-violet/90 transition"
          >
            Create account &amp; join
          </button>
          {acceptMsg && <p className="text-[11px] text-red-600">{acceptMsg}</p>}
        </div>
      )}
      {mode === "existing" && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50/50 p-5 dark:border-amber-500/20 dark:bg-amber-500/[0.06] space-y-3">
          <p className="text-[14px] font-semibold text-amber-700 dark:text-amber-300">Account already exists</p>
          <p className="text-[13px] text-ink/60 dark:text-fog/60">This email is already registered. Please sign in first, then return to accept the invite.</p>
          <a href="/auth/login" className="inline-block rounded-lg bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white hover:bg-deep-violet/90">Sign in</a>
        </div>
      )}
      {mode === "done" && (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-5 dark:border-emerald-500/20 dark:bg-emerald-500/[0.06]">
          <p className="text-[15px] font-bold text-emerald-700 dark:text-emerald-300">Welcome to the team!</p>
          <p className="text-[13px] text-ink/60 dark:text-fog/60 mt-1">You are now a member of this workspace.</p>
        </div>
      )}
    </div>
  );
}
