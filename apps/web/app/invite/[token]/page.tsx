"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { getAccessToken, useAuth } from "@/lib/auth-context";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface InvitePreview {
  email: string;
  business_name?: string | null;
  inviter_name?: string | null;
  role_name?: string | null;
  expires_at?: string | null;
  account_exists?: boolean;
}

type Mode = "loading" | "invalid" | "preview" | "new" | "signin" | "done";

function detailText(d: unknown, fallback: string): string {
  if (typeof d === "string") return d;
  if (d && typeof d === "object") {
    const o = d as Record<string, unknown>;
    if (typeof o.message === "string") return o.message;
  }
  return fallback;
}

export default function InvitePage() {
  const routeParams = useParams<{ token: string }>();
  const { user, loading: authLoading, logout } = useAuth();
  const token = routeParams?.token || "";

  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [mode, setMode] = useState<Mode>(() => (token ? "loading" : "invalid"));
  const [password, setPassword] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    (async () => {
      try {
        const res = await fetch(`${API}/api/v1/team/invites/preview?token=${encodeURIComponent(token)}`, { credentials: "include" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          setMsg(detailText(data?.detail, "This invite link is invalid or was already used."));
          setMode("invalid");
          return;
        }
        setPreview(data as InvitePreview);
        setMode("preview");
      } catch {
        setMsg("Could not load this invite — check your connection and try again.");
        setMode("invalid");
      }
    })();
  }, [token]);

  const emailMatches =
    !!user?.email && !!preview?.email && user.email.toLowerCase() === preview.email.toLowerCase();

  const accept = async (extra: Record<string, unknown>, withBearer: boolean): Promise<boolean> => {
    setBusy(true); setMsg("");
    try {
      const accessToken = withBearer ? getAccessToken() : null;
      const res = await fetch(`${API}/api/v1/team/invites/accept`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        credentials: "include",
        body: JSON.stringify({ token, ...extra }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.ok) {
        setMode("done");
        return true;
      }
      const d = data?.detail as unknown;
      const code = d && typeof d === "object" ? (d as Record<string, unknown>).code : undefined;
      if (res.status === 401 || res.status === 403 || code === "login_required") {
        setMsg(detailText(d, "Please sign in with the invited account."));
        setMode("signin");
        return false;
      }
      setMsg(detailText(d, "Could not accept this invite."));
      return false;
    } catch {
      setMsg("Network error — could not accept invite.");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const passwordValid = password.length >= 8;
  const expiresLabel = preview?.expires_at ? new Date(preview.expires_at).toLocaleDateString() : null;

  return (
    <div className="mx-auto max-w-md p-6 space-y-6">
      <h1 className="text-[20px] font-bold text-ink dark:text-fog">Team invite</h1>

      {mode === "loading" && <p className="text-[13px] text-ink/40 dark:text-fog/40">Loading invite…</p>}

      {mode === "invalid" && (
        <div className="rounded-2xl border border-red-200 bg-red-50/50 p-5 dark:border-red-500/20 dark:bg-red-500/[0.06]">
          <p className="text-[14px] font-semibold text-red-700 dark:text-red-300">This invite cannot be used</p>
          <p className="mt-1 text-[13px] text-ink/60 dark:text-fog/60">{msg || "This invite link is invalid or was already used."}</p>
        </div>
      )}

      {mode === "preview" && (
        <div className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm dark:border-fog/10 dark:bg-ink">
          <p className="text-[13px] text-ink/70 dark:text-fog/70">
            <strong>{preview?.business_name || "A workspace"}</strong> invited you, via{" "}
            <strong>{preview?.inviter_name || "the workspace owner"}</strong>.
          </p>
          <div className="mt-3 flex items-center gap-2">
            <span className="rounded-full bg-deep-violet/10 px-2.5 py-0.5 text-[11px] font-semibold text-deep-violet">
              {preview?.role_name || "member"}
            </span>
            {expiresLabel && <span className="text-[11px] text-ink/40 dark:text-fog/40">Expires {expiresLabel}</span>}
          </div>
          <p className="mt-3 text-[12px] text-ink/50 dark:text-fog/50">For: {preview?.email}</p>

          {authLoading ? (
            <p className="mt-4 text-[12px] text-ink/40 dark:text-fog/40">Checking your session…</p>
          ) : preview?.account_exists ? (
            emailMatches ? (
              <button
                onClick={() => accept({}, true)}
                disabled={busy}
                className="mt-4 w-full rounded-lg bg-deep-violet px-4 py-2.5 text-[13px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-40"
              >
                {busy ? "Joining…" : `Join as ${preview?.email}`}
              </button>
            ) : (
              <button
                onClick={() => { setMsg(""); setMode("signin"); }}
                className="mt-4 w-full rounded-lg bg-deep-violet px-4 py-2.5 text-[13px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90"
              >
                Continue to sign in
              </button>
            )
          ) : (
            <button
              onClick={() => setMode("new")}
              className="mt-4 w-full rounded-lg bg-deep-violet px-4 py-2.5 text-[13px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90"
            >
              Accept invite
            </button>
          )}
        </div>
      )}

      {mode === "new" && (
        <div className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm dark:border-fog/10 dark:bg-ink space-y-4">
          <p className="text-[14px] font-semibold text-ink dark:text-fog">Create your account</p>
          <div className="space-y-2">
            <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Email</label>
            <input
              value={preview?.email || ""}
              readOnly
              className="w-full rounded-lg border border-ink/10 bg-ink/[0.04] px-3 py-2 text-[13px] text-ink/50 dark:border-fog/10 dark:bg-fog/[0.04] dark:text-fog/50"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2">
              <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">First name</label>
              <input
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                placeholder="Optional"
                className="w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog"
              />
            </div>
            <div className="space-y-2">
              <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Last name</label>
              <input
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                placeholder="Optional"
                className="w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 dark:border-fog/10 dark:bg-ink dark:text-fog"
              />
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              className="w-full rounded-lg border border-ink/10 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.08] dark:border-fog/10 dark:bg-ink dark:text-fog"
            />
            {password && !passwordValid && <p className="text-[11px] text-red-600">Password must be at least 8 characters.</p>}
          </div>
          <button
            onClick={() => accept({ password, first_name: firstName || undefined, last_name: lastName || undefined }, false)}
            disabled={!passwordValid || busy}
            className="w-full rounded-lg bg-deep-violet px-4 py-2.5 text-[13px] font-semibold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-40"
          >
            {busy ? "Creating account…" : "Create account & join"}
          </button>
          {msg && <p className="text-[11px] text-red-600">{msg}</p>}
        </div>
      )}

      {mode === "signin" && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50/50 p-5 dark:border-amber-500/20 dark:bg-amber-500/[0.06] space-y-3">
          <p className="text-[14px] font-semibold text-amber-700 dark:text-amber-300">
            {user && emailMatches ? "Finish joining" : "Sign in to continue"}
          </p>
          {user && emailMatches ? (
            <p className="text-[13px] text-ink/60 dark:text-fog/60">
              You are signed in as <strong>{user.email}</strong>. Finish joining{" "}
              <strong>{preview?.business_name || "the workspace"}</strong>.
            </p>
          ) : user ? (
            <p className="text-[13px] text-ink/60 dark:text-fog/60">
              You are signed in as <strong>{user.email}</strong>, but this invite is for{" "}
              <strong>{preview?.email || "another account"}</strong>. Sign out and sign in with the invited account.
            </p>
          ) : (
            <p className="text-[13px] text-ink/60 dark:text-fog/60">
              This email already has a Sayvors account. Sign in as <strong>{preview?.email}</strong> to join{" "}
              <strong>{preview?.business_name || "the workspace"}</strong>.
            </p>
          )}
          {msg && <p className="text-[11px] text-red-600">{msg}</p>}
          <div className="flex gap-2">
            {user && emailMatches ? (
              <button
                onClick={() => accept({}, true)}
                disabled={busy}
                className="rounded-lg bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
              >
                {busy ? "Joining…" : `Join as ${preview?.email}`}
              </button>
            ) : user ? (
              <button
                onClick={() => logout(false, `/invite/${token}`)}
                className="rounded-lg bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90"
              >
                Sign out
              </button>
            ) : (
              <a
                href={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}
                className="rounded-lg bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90"
              >
                Sign in
              </a>
            )}
          </div>
        </div>
      )}

      {mode === "done" && (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50/40 p-5 dark:border-emerald-500/20 dark:bg-emerald-500/[0.06]">
          <p className="text-[15px] font-bold text-emerald-700 dark:text-emerald-300">Welcome to the team!</p>
          <p className="mt-1 text-[13px] text-ink/60 dark:text-fog/60">You are now a member of this workspace.</p>
          <a
            href="/dashboard"
            className="mt-4 inline-block rounded-lg bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90"
          >
            Go to dashboard
          </a>
        </div>
      )}
    </div>
  );
}
