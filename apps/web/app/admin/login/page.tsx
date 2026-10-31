"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import LogoLoader from "@/components/LogoLoader";
import { adminLogin } from "@/lib/api-admin";

export default function AdminLoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || !username.trim() || !password) return;
    setBusy(true);
    setError(null);
    try {
      await adminLogin(username.trim(), password);
      router.replace("/admin/plans");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-[24px] bg-white p-7 shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_24px_48px_-16px_rgba(20,16,31,0.35)] dark:bg-ink dark:shadow-[0_1px_0_rgba(255,255,255,0.08)_inset,0_24px_48px_-16px_rgba(0,0,0,0.8)]"
      >
        <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-ink/40 dark:text-fog/40">
          Platform admin
        </p>
        <h1 className="mt-1 text-[22px] font-extrabold tracking-tight">Sign in</h1>
        <p className="mt-1 text-[13px] text-ink/55 dark:text-fog/55">
          Operator account — separate from any tenant login.
        </p>
        {error && (
          <p role="alert" className="mt-4 rounded-2xl bg-[#FF4F6E]/10 px-4 py-3 text-[12px] font-medium text-[#C4304B] dark:text-[#FF8FA3]">
            {error}
          </p>
        )}
        <label className="mt-5 block">
          <span className="mb-1 block text-[12px] font-semibold">Username</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            className="input-field h-11 w-full"
          />
        </label>
        <label className="mt-3 block">
          <span className="mb-1 block text-[12px] font-semibold">Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            className="input-field h-11 w-full"
          />
        </label>
        <button
          type="submit"
          disabled={busy || !username.trim() || !password}
          className="mt-5 flex h-11 w-full items-center justify-center gap-2 rounded-[20px] bg-deep-violet text-[13px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] disabled:opacity-40 focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
        >
          {busy ? <LogoLoader size={18} /> : "Sign in"}
        </button>
      </form>
    </div>
  );
}
