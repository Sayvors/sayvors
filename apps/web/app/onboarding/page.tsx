"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import OnboardingProgress from "@/components/onboarding/OnboardingProgress";
import ChannelCard from "@/components/onboarding/ChannelCard";
import DatabankStep from "@/components/onboarding/DatabankStep";
import AutoReplyToggle from "@/components/onboarding/AutoReplyToggle";
import { useAuth, getAccessToken } from "@/lib/auth-context";
import { apiFetch } from "@/lib/api-rag";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STEPS = ["Welcome", "Connect", "Databank", "Auto-Reply"];
const STORAGE_KEY = "onboarding_step";

const channels = [
  { name: "Google Reviews", slug: "google", icon: "\u2B50", color: "from-amber-400 to-orange-500", soon: false },
  { name: "Instagram", slug: "instagram", icon: "\u{1F4F7}", color: "from-purple-500 to-pink-500", soon: true },
  { name: "Facebook Messenger", slug: "facebook", icon: "\u{1F4AC}", color: "from-blue-500 to-blue-600", soon: true },
  { name: "X / Twitter", slug: "x", icon: "X", color: "from-ink to-ink dark:from-fog dark:to-fog", soon: true },
];

function Confetti() {
  return (
    <div className="pointer-events-none fixed inset-0 z-50 overflow-hidden">
      {Array.from({ length: 60 }).map((_, i) => (
        <div
          key={i}
          className="absolute animate-bounce rounded-sm"
          style={{
            left: `${Math.random() * 100}%`,
            top: `-5%`,
            width: `${6 + Math.random() * 6}px`,
            height: `${6 + Math.random() * 6}px`,
            backgroundColor: ["#7C3AED", "#D946EF", "#F97316", "#10B981", "#3B82F6", "#EAB308"][i % 6],
            animationDuration: `${2 + Math.random() * 3}s`,
            animationDelay: `${Math.random() * 2}s`,
          }}
        />
      ))}
    </div>
  );
}

export default function OnboardingPage() {
  const router = useRouter();
  const { user, loading, refreshAuth } = useAuth();
  const [step, setStep] = useState(0);
  const [googleConnected, setGoogleConnected] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    if (!loading && !user) {
      router.replace("/login");
    }
  }, [user, loading, router]);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved !== null) setStep(Number(saved));
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, String(step));
  }, [step]);

  // Check real connection state + callback result (we return here after Google OAuth)
  const checkGoogle = useCallback(async () => {
    try {
      const data = await apiFetch("/api/v1/channels/?limit=100");
      const has = (data.channels ?? []).some(
        (c: { platform: string; status: string }) => c.platform === "google_reviews" && c.status === "active"
      );
      setGoogleConnected(has);
    } catch { /* backend down / not logged in */ }
  }, []);

  useEffect(() => {
    checkGoogle();
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("google_connected");
    const err = params.get("google_error");
    if (connected !== null) {
      setBanner({ kind: "ok", text: `Google Reviews connected (${connected} location${Number(connected) === 1 ? "" : "s"})! 🎉` });
      setStep(1);
      window.history.replaceState({}, "", "/onboarding");
    } else if (err) {
      const messages: Record<string, string> = {
        no_business_account: "That Google account has no Business Profile. Create one at business.google.com, then retry.",
        token_exchange_failed: "Google rejected the connection — please try again.",
        access_denied: "You cancelled the Google consent screen.",
        invalid_state: "The connect session expired — click Connect again.",
      };
      setBanner({ kind: "err", text: messages[err] ?? `Google connect failed (${err}).` });
      setStep(1);
      window.history.replaceState({}, "", "/onboarding");
    }
  }, [checkGoogle]);

  const saveAndContinue = async () => {
    try {
      await apiFetch("/api/v1/auth/me", {
        method: "PATCH",
        body: JSON.stringify({ onboarded: true }),
      });
      await refreshAuth();
    } catch { /* best effort */ }
    localStorage.removeItem(STORAGE_KEY);
    router.replace("/dashboard");
  };

  const goNext = () => {
    if (step < STEPS.length - 1) setStep(step + 1);
    else saveAndContinue();
  };

  const skip = () => saveAndContinue();

  const handleConnect = (slug: string) => {
    if (slug !== "google") return;
    const token = getAccessToken();
    if (!token) {
      setBanner({ kind: "err", text: "Please log in again." });
      return;
    }
    // Real OAuth: Google consent → callback → back to /onboarding?google_connected=N
    window.location.href = `${API_URL}/api/v1/channels/google/connect?token=${encodeURIComponent(token)}&next=/onboarding`;
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-fog px-4 py-10 dark:bg-ink">
      <Confetti />

      {/* Logo */}
      <div className="mb-6 flex items-center gap-2">
        <Image src="/Sayvors_Icon.png" alt="Sayvors" width={28} height={28} className="rounded-md" />
        <span className="text-[16px] font-bold text-ink dark:text-fog">Sayvors</span>
      </div>

      {/* Progress */}
      <div className="mb-8">
        <OnboardingProgress currentStep={step} totalSteps={STEPS.length} stepLabels={STEPS} />
      </div>

      {banner && (
        <div className="mb-5 w-full max-w-lg">
          <div
            className={`rounded-xl border p-3 text-[13px] ${
              banner.kind === "ok"
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-red-200 bg-red-50 text-red-700"
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <span>{banner.text}</span>
              <button className="shrink-0 text-[12px] underline underline-offset-2" onClick={() => setBanner(null)}>
                dismiss
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step content */}
      <div className="w-full max-w-lg">
        {/* Step 0: Welcome */}
        {step === 0 && (
          <div className="text-center space-y-6">
            <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet to-magenta text-[36px] text-white shadow-lg">
              {"\u2728"}
            </div>
            <div>
              <h1 className="text-[24px] font-bold text-ink dark:text-fog">Welcome to Sayvors</h1>
              <p className="mt-2 text-[14px] text-ink/50 dark:text-fog/50">
                Your AI-powered assistant that handles messages, reviews, and customer conversations — so you don&apos;t have to.
              </p>
            </div>
            <p className="text-[13px] text-ink/40 dark:text-fog/40">Let&apos;s get you set up in 3 quick steps.</p>
          </div>
        )}

        {/* Step 1: Connect Channels */}
        {step === 1 && (
          <div className="space-y-4">
            <div className="mb-6 text-center">
              <h2 className="text-[20px] font-bold text-ink dark:text-fog">Connect your channels</h2>
              <p className="mt-1 text-[13px] text-ink/50 dark:text-fog/50">
                Connect Google Reviews so your AI can answer your customers.
              </p>
            </div>
            {channels.map((ch) => (
              <ChannelCard
                key={ch.slug}
                name={ch.name}
                slug={ch.slug}
                icon={ch.icon}
                color={ch.color}
                soon={ch.soon}
                connected={ch.slug === "google" ? googleConnected : false}
                onConnect={() => handleConnect(ch.slug)}
              />
            ))}
          </div>
        )}

        {/* Step 2: Databank */}
        {step === 2 && (
          <div className="space-y-4">
            <div className="mb-6 text-center">
              <h2 className="text-[20px] font-bold text-ink dark:text-fog">Feed your AI brain</h2>
              <p className="mt-1 text-[13px] text-ink/50 dark:text-fog/50">Upload docs so your AI answers from real knowledge.</p>
            </div>
            <DatabankStep onComplete={goNext} />
          </div>
        )}

        {/* Step 3: Auto-Reply */}
        {step === 3 && (
          <div className="space-y-4">
            <div className="mb-6 text-center">
              <h2 className="text-[20px] font-bold text-ink dark:text-fog">Turn on Auto-Reply</h2>
              <p className="mt-1 text-[13px] text-ink/50 dark:text-fog/50">Your AI will respond automatically on chosen channels.</p>
            </div>
            <AutoReplyToggle onComplete={goNext} />
          </div>
        )}
      </div>

      {/* Bottom buttons */}
      {step !== 2 && (
        <div className="mt-8 flex items-center gap-4">
          <button onClick={skip} className="text-[12px] text-ink/30 hover:text-ink/50 dark:text-fog/30 dark:hover:text-fog/50">
            Skip for now
          </button>
          {step !== 3 && (
            <button
              onClick={goNext}
              className="rounded-xl bg-deep-violet px-6 py-2.5 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90"
            >
              {step === 0 ? "Let's go" : "Continue"}
            </button>
          )}
        </div>
      )}
      {step === 2 && (
        <div className="mt-8">
          <button onClick={skip} className="text-[12px] text-ink/30 hover:text-ink/50 dark:text-fog/30 dark:hover:text-fog/50">
            Skip for now
          </button>
        </div>
      )}
    </div>
  );
}
