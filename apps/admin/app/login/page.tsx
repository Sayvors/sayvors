"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { adminLogin, setAdminToken } from "@/lib/admin-api";

export default function AdminLoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) return;
    setBusy(true);
    setError(null);
    try {
      const res = await adminLogin(password);
      setAdminToken(res.access_token);
      router.replace("/overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f3f0ff] p-4">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-4 rounded-[6px] border-2 border-white bg-white/80 p-6 shadow-lg shadow-deep-violet/[0.08] backdrop-blur-sm"
      >
        <div>
          <h1 className="text-[18px] font-bold text-ink">Sayvors Admin</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">Platform overview. Operator access only.</p>
        </div>
        <div>
          <label className="mb-1 block text-[12px] font-medium text-ink/60">Admin password</label>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            autoFocus
            className="input-field"
          />
        </div>
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy || !password} className="btn-primary w-full justify-center disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
