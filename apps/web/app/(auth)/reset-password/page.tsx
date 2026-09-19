"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { validatePassword } from "@/lib/validation";
import { Suspense } from "react";
import LogoLoader from "@/components/LogoLoader";

function ResetPasswordContent() {
  const searchParams = useSearchParams();
  const { resetPassword } = useAuth();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success">("idle");
  const [error, setError] = useState("");

  const token = searchParams.get("token");
  const validation = validatePassword(password);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      setError("Passwords don't match");
      return;
    }
    if (!validation.valid) {
      setError("Password doesn't meet requirements");
      return;
    }
    if (!token) {
      setError("No reset token found");
      return;
    }

    setStatus("loading");
    setError("");
    try {
      await resetPassword(token, password);
      setStatus("success");
    } catch (err: any) {
      setError(err.message || "Reset failed");
      setStatus("idle");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-fog dark:bg-ink">
      <div className="w-full max-w-sm rounded-2xl border border-ink/[0.06] bg-white p-8 dark:border-fog/[0.06] dark:bg-ink">
        <div className="mb-6 text-center">
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Reset Password</h1>
          <p className="mt-1 text-[13px] text-ink/45 dark:text-fog/45">Enter your new password below.</p>
        </div>

        {status === "success" ? (
          <div className="flex flex-col items-center gap-3 py-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 dark:bg-emerald-900/20">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-6 w-6 text-emerald-600">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <p className="text-[13px] text-ink/50 dark:text-fog/50">Password reset successfully!</p>
            <a href="/login" className="mt-2 text-[13px] font-medium text-deep-violet hover:underline">
              Go to Login
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">New Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="mt-1 h-10 w-full rounded-lg border border-ink/[0.08] bg-fog/30 px-3.5 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.06] dark:border-fog/[0.08] dark:bg-ink/40 dark:text-fog dark:placeholder:text-fog/25 dark:focus:bg-ink"
                placeholder="••••••••"
              />
              {password && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {["At least 8 characters", "One uppercase", "One lowercase", "One number"].map((rule) => (
                    <span
                      key={rule}
                      className={`text-[10px] ${
                        validation.errors.includes(rule) ? "text-coral/60" : "text-emerald-600"
                      }`}
                    >
                      {validation.errors.includes(rule) ? "• " : "✓ "}{rule}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div>
              <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Confirm Password</label>
              <input
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                className="mt-1 h-10 w-full rounded-lg border border-ink/[0.08] bg-fog/30 px-3.5 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.06] dark:border-fog/[0.08] dark:bg-ink/40 dark:text-fog dark:placeholder:text-fog/25 dark:focus:bg-ink"
                placeholder="••••••••"
              />
              {confirm && password !== confirm && (
                <p className="mt-1 text-[10px] text-coral">Passwords don&apos;t match</p>
              )}
            </div>

            {error && <p className="text-[12px] text-coral">{error}</p>}

            <button
              type="submit"
              disabled={status === "loading" || !validation.valid || password !== confirm}
              className="flex h-10 w-full items-center justify-center rounded-lg bg-gradient-to-r from-deep-violet to-magenta text-[13px] font-semibold text-white transition hover:shadow-md disabled:opacity-50"
            >
              {status === "loading" ? "Resetting..." : "Reset Password"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center bg-fog dark:bg-ink">
        <LogoLoader size={40} />
      </div>
    }>
      <ResetPasswordContent />
    </Suspense>
  );
}
