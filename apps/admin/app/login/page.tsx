"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { adminLogin } from "@/lib/admin-api";

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
      if (!res || typeof res.expires_in_minutes !== "number") {
        throw new Error("Unexpected login response. Please try again.");
      }
      router.replace("/overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--ui-page)] p-4">
      <form
        onSubmit={submit}
        className="panel w-full max-w-sm space-y-4 p-6"
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
          <p role="alert" className="rounded-[2px] bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">
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
