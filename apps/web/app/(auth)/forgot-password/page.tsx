"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";

export default function ForgotPasswordPage() {
  const { forgotPassword } = useAuth();
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "sent">("idle");
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("loading");
    setError("");
    try {
      await forgotPassword(email);
      setStatus("sent");
    } catch (err: any) {
      setError(err.message || "Something went wrong");
      setStatus("idle");
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-fog dark:bg-ink">
      <div className="w-full max-w-sm rounded-2xl border border-ink/[0.06] bg-white p-8 dark:border-fog/[0.06] dark:bg-ink">
        <div className="mb-6 text-center">
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Forgot Password</h1>
          <p className="mt-1 text-[13px] text-ink/45 dark:text-fog/45">
            Enter your email and we&apos;ll send you a reset link.
          </p>
        </div>

        {status === "sent" ? (
          <div className="flex flex-col items-center gap-3 py-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 dark:bg-emerald-900/20">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-6 w-6 text-emerald-600">
                <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
              </svg>
            </div>
            <p className="text-[13px] text-ink/50 dark:text-fog/50">
              If <span className="font-medium text-ink dark:text-fog">{email}</span> is registered, you&apos;ll receive a reset link.
            </p>
            <a href="/login" className="mt-2 text-[13px] font-medium text-deep-violet hover:underline">
              Back to Login
            </a>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="mt-1 h-10 w-full rounded-lg border border-ink/[0.08] bg-fog/30 px-3.5 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.06] dark:border-fog/[0.08] dark:bg-ink/40 dark:text-fog dark:placeholder:text-fog/25 dark:focus:bg-ink"
                placeholder="you@example.com"
              />
            </div>

            {error && (
              <p className="text-[12px] text-coral">{error}</p>
            )}

            <button
              type="submit"
              disabled={status === "loading"}
              className="flex h-10 w-full items-center justify-center rounded-lg bg-gradient-to-r from-deep-violet to-magenta text-[13px] font-semibold text-white transition hover:shadow-md disabled:opacity-50"
            >
              {status === "loading" ? "Sending..." : "Send Reset Link"}
            </button>

            <p className="text-center text-[12px] text-ink/40 dark:text-fog/40">
              <a href="/login" className="font-medium text-deep-violet hover:underline">
                Back to Login
              </a>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
