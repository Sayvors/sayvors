"use client";

import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useEffect, useState, Suspense } from "react";
import LogoLoader from "@/components/LogoLoader";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const { verifyEmail } = useAuth();
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    const token = searchParams.get("token");
    if (!token) {
      setStatus("error");
      setMessage("No verification token found");
      return;
    }

    verifyEmail(token)
      .then(() => {
        setStatus("success");
        setMessage("Email verified successfully!");
      })
      .catch((err) => {
        setStatus("error");
        setMessage(err.message || "Verification failed");
      });
  }, [searchParams, verifyEmail]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-fog dark:bg-ink">
      <div className="w-full max-w-sm rounded-2xl border border-ink/[0.06] bg-white p-8 text-center dark:border-fog/[0.06] dark:bg-ink">
        {status === "loading" && (
          <div className="flex flex-col items-center gap-3">
            <LogoLoader size={40} label="Verifying your email…" showText />
          </div>
        )}
        {status === "success" && (
          <div className="flex flex-col items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 dark:bg-emerald-900/20">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-6 w-6 text-emerald-600">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </div>
            <p className="text-[14px] font-semibold text-ink dark:text-fog">{message}</p>
            <a href="/login" className="mt-2 text-[13px] font-medium text-deep-violet hover:underline">
              Go to Login
            </a>
          </div>
        )}
        {status === "error" && (
          <div className="flex flex-col items-center gap-3">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-coral/10">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-6 w-6 text-coral">
                <circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" />
              </svg>
            </div>
            <p className="text-[14px] font-semibold text-ink dark:text-fog">{message}</p>
            <a href="/login" className="mt-2 text-[13px] font-medium text-deep-violet hover:underline">
              Go to Login
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={
      <div className="flex min-h-screen items-center justify-center bg-fog dark:bg-ink">
        <LogoLoader size={40} />
      </div>
    }>
      <VerifyEmailContent />
    </Suspense>
  );
}
