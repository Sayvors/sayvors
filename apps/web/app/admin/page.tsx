"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { adminHasSession, adminLogin } from "@/lib/admin-api";
import LogoLoader from "@/components/LogoLoader";

export default function AdminLoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Already logged in → straight to the panel.
    if (adminHasSession()) router.replace("/admin/overview");
  }, [router]);

  async function submit() {
    if (!password) return;
    setBusy(true);
    setError(null);
    try {
      await adminLogin(password);
      router.replace("/admin/overview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-3xl border border-white bg-white/90 p-6 shadow-sm">
        <h1 className="text-[18px] font-bold text-ink">
          Sayvors <span className="text-deep-violet">Admin</span>
        </h1>
        <p className="mt-1 text-[12px] text-ink/50">Platform operator access. Password only — separate from tenant accounts.</p>
        <form
          onSubmit={(e) => { e.preventDefault(); void submit(); }}
          className="mt-5 space-y-3"
        >
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Admin password"
            className="input-field"
            autoFocus
            autoComplete="current-password"
          />
          {error && <p className="rounded-lg bg-coral/10 px-3 py-2 text-[12px] font-medium text-coral">{error}</p>}
          <button
            type="submit"
            disabled={busy || !password}
            className="w-full rounded-xl bg-deep-violet px-4 py-2.5 text-[13px] font-bold text-white transition hover:opacity-90 disabled:opacity-40"
          >
            {busy ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Checking…</span> : "Log in"}
          </button>
        </form>
      </div>
    </div>
  );
}
