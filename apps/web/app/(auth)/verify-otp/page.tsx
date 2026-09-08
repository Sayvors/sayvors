"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import LogoLoader from "@/components/LogoLoader";

function VerifyOtpInner() {
  const router = useRouter();
  const params = useSearchParams();
  const { verifyOtp, resendOtp } = useAuth();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  useEffect(() => {
    setEmail(params.get("email") ?? "");
  }, [params]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setError("");
    if (code.trim().length < 4) {
      setError("Enter the code from your email.");
      return;
    }
    setBusy(true);
    try {
      await verifyOtp(email.trim(), code.trim());
      setDone(true);
      setTimeout(() => router.push("/dashboard"), 1500);
    } catch (err: any) {
      setError(err.message || "Verification failed");
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    if (!email.trim() || cooldown > 0) return;
    setError("");
    setResending(true);
    try {
      await resendOtp(email.trim());
      setCooldown(60);
    } catch (err: any) {
      setError(err.message || "Could not resend code");
    } finally {
      setResending(false);
    }
  };

  if (done) {
    return (
      <div className="flex flex-col items-center text-center">
        <div className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-emerald-500">
          <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6"><path d="M4.5 12.75l6 6 9-13.5" /></svg>
        </div>
        <h2 className="mt-4 text-lg font-semibold text-ink">Email verified!</h2>
        <p className="mt-1.5 text-[13px] text-ink/55">Taking you to your dashboard...</p>
      </div>
    );
  }

  return (
    <>
      <div className="mb-8">
        <h1 className="text-[22px] font-semibold tracking-tight text-ink">Check your email</h1>
        <p className="mt-1.5 text-[14px] text-ink/55">
          We sent a 6-digit code to <span className="font-medium text-ink">{email || "your email"}</span>.
          Enter it below to verify your account.
        </p>
      </div>

      <form onSubmit={submit} noValidate className="space-y-3.5">
        <div className="space-y-1.5">
          <label htmlFor="otp-email" className="block text-[13px] font-medium text-ink/70">Email</label>
          <input
            id="otp-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="you@company.com" autoComplete="email"
            className="h-11 w-full rounded-lg border border-ink/[0.12] bg-white px-3.5 text-[14px] text-ink outline-none transition placeholder:text-ink/35 focus:border-deep-violet/40 focus:ring-[3px] focus:ring-deep-violet/[0.08]"
          />
        </div>
        <div className="space-y-1.5">
          <label htmlFor="otp-code" className="block text-[13px] font-medium text-ink/70">Verification code</label>
          <input
            id="otp-code" type="text" inputMode="numeric" value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="000000" autoComplete="one-time-code" autoFocus
            className="h-12 w-full rounded-lg border border-ink/[0.12] bg-white px-3.5 text-center font-mono text-[20px] tracking-[0.3em] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 focus:ring-[3px] focus:ring-deep-violet/[0.08]"
          />
        </div>
        <button type="submit" disabled={busy}
          className="h-11 w-full rounded-lg bg-ink text-[14px] font-medium text-white transition hover:bg-ink/90 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50">
          {busy ? <span className="inline-flex items-center gap-2"><LogoLoader size={18} /> Verifying...</span> : "Verify email"}
        </button>
        {error && <p className="text-center text-[12px] font-medium text-coral">{error}</p>}
      </form>

      <p className="mt-5 text-center text-[13px] text-ink/50">
        Didn{"\u2019"}t get a code?{" "}
        <button type="button" onClick={resend} disabled={resending || cooldown > 0 || !email.trim()}
          className="font-medium text-ink/70 hover:text-ink disabled:cursor-not-allowed disabled:opacity-40">
          {resending ? "Sending..." : cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
        </button>
      </p>
      <p className="mt-4 text-center text-[13px] text-ink/50">
        <Link href="/login" className="font-medium text-ink/70 hover:text-ink">Back to sign in</Link>
      </p>
    </>
  );
}

export default function VerifyOtpPage() {
  return (
    <Suspense>
      <VerifyOtpInner />
    </Suspense>
  );
}
