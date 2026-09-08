"use client";

import { Suspense, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

interface LocationOption {
  id: string;
  name: string;
  address: string;
  status: string;
}

interface VerificationStatus {
  location_id: string;
  verified: boolean;
  pending: boolean;
  method: string | null;
  verified_at: string | null;
  available_methods: string[];
  attempts: number;
}

const MOCK_LOCATIONS: LocationOption[] = [
  { id: "loc_1", name: "Sayvors Al Malqa", address: "Al Malqa, Riyadh", status: "active" },
];

export default function VerificationPage() {
  return (
    <Suspense>
      <VerificationInner />
    </Suspense>
  );
}

function VerificationInner() {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState<VerificationStatus | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/locations/?limit=100");
        if (!cancelled) {
          setLocations(data.locations ?? []);
          if (data.locations?.length) setSelectedId(data.locations[0].id);
        }
      } catch {
        setLocations(MOCK_LOCATIONS);
        setSelectedId(MOCK_LOCATIONS[0].id);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch(`/api/v1/locations/${selectedId}/verification`);
        if (!cancelled) setStatus(data);
      } catch {
        if (!cancelled) setStatus({
          location_id: selectedId!,
          verified: false,
          pending: false,
          method: null,
          verified_at: null,
          available_methods: ["postcard", "phone", "email"],
          attempts: 0,
        });
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  const requestVerification = async (method: string) => {
    setRequesting(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/verification`, {
        method: "POST",
        body: JSON.stringify({ method }),
      });
      setStatus((prev) => prev ? { ...prev, pending: true, method } : null);
      setBanner({ kind: "ok", text: `Verification requested via ${method}. Check your ${method === "postcard" ? "mail" : method}.` });
    } catch {
      setBanner({ kind: "err", text: "Could not request verification." });
    }
    setRequesting(false);
  };

  if (loading) return <div className="flex h-full items-center justify-center"><LogoLoader size={32} /></div>;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5 max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Verification</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
            Verify your business to unlock full Google Business features.
          </p>
        </div>
        <div className="relative">
          <select
            value={selectedId ?? ""}
            onChange={(e) => setSelectedId(e.target.value)}
            className="w-56 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
          >
            {locations.map((loc) => (
              <option key={loc.id} value={loc.id}>{loc.name}</option>
            ))}
          </select>
          <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </div>
      </div>

      {/* Banner */}
      {banner && (
        <div className={`rounded-xl border p-3 text-[13px] ${banner.kind === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`}>
          <div className="flex items-center justify-between gap-3">
            <span>{banner.text}</span>
            <button className="shrink-0 text-[12px] underline underline-offset-2" onClick={() => setBanner(null)}>dismiss</button>
          </div>
        </div>
      )}

      {/* Status Card */}
      <div className="rounded-2xl border border-ink/[0.06] bg-white p-6 dark:border-fog/[0.06] dark:bg-ink">
        <div className="flex items-center gap-4">
          <div className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl ${
            status?.verified
              ? "bg-emerald-100 dark:bg-emerald-500/10"
              : status?.pending
              ? "bg-amber-100 dark:bg-amber-500/10"
              : "bg-ink/[0.04] dark:bg-fog/[0.04]"
          }`}>
            {status?.verified ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 text-emerald-600 dark:text-emerald-400">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
            ) : status?.pending ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 text-amber-600 dark:text-amber-400">
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 text-ink/30 dark:text-fog/30">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
            )}
          </div>
          <div>
            <h2 className="text-[16px] font-bold text-ink dark:text-fog">
              {status?.verified ? "Verified" : status?.pending ? "Verification Pending" : "Not Verified"}
            </h2>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">
              {status?.verified
                ? `Verified${status.verified_at ? ` on ${new Date(status.verified_at).toLocaleDateString()}` : ""}`
                : status?.pending
                ? `Verification via ${status.method} is in progress...`
                : "Request verification to prove ownership of this location."}
            </p>
          </div>
        </div>

        {status?.attempts ? (
          <p className="mt-3 text-[11px] text-ink/30 dark:text-fog/30">{status.attempts} previous attempt{status.attempts > 1 ? "s" : ""}</p>
        ) : null}
      </div>

      {/* Verification Methods */}
      {!status?.verified && !status?.pending && (
        <div className="space-y-3">
          <h3 className="text-[14px] font-semibold text-ink dark:text-fog">Choose Verification Method</h3>
          <p className="text-[12px] text-ink/40 dark:text-fog/40">Google will verify your connection to this business.</p>

          <div className="grid gap-3">
            {/* Postcard */}
            <button
              onClick={() => requestVerification("postcard")}
              disabled={requesting}
              className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 text-left transition hover:border-deep-violet/20 hover:bg-deep-violet/[0.02] dark:border-fog/[0.06] dark:bg-ink dark:hover:border-deep-violet/20"
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-deep-violet/10">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5 text-deep-violet">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
              </div>
              <div className="flex-1">
                <p className="text-[13px] font-semibold text-ink dark:text-fog">Postcard by Mail</p>
                <p className="text-[11px] text-ink/40 dark:text-fog/40">Receive a postcard with a verification code. Takes 5–14 days.</p>
              </div>
              <span className="rounded-full bg-deep-violet px-3 py-1 text-[11px] font-semibold text-white">Select</span>
            </button>

            {/* Phone */}
            <button
              onClick={() => requestVerification("phone")}
              disabled={requesting}
              className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 text-left transition hover:border-deep-violet/20 hover:bg-deep-violet/[0.02] dark:border-fog/[0.06] dark:bg-ink dark:hover:border-deep-violet/20"
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-100 dark:bg-emerald-500/10">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5 text-emerald-600 dark:text-emerald-400">
                  <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
                </svg>
              </div>
              <div className="flex-1">
                <p className="text-[13px] font-semibold text-ink dark:text-fog">Phone Call</p>
                <p className="text-[11px] text-ink/40 dark:text-fog/40">Receive an automated call with a code. Instant.</p>
              </div>
              <span className="rounded-full bg-deep-violet px-3 py-1 text-[11px] font-semibold text-white">Select</span>
            </button>

            {/* Email */}
            <button
              onClick={() => requestVerification("email")}
              disabled={requesting}
              className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 text-left transition hover:border-deep-violet/20 hover:bg-deep-violet/[0.02] dark:border-fog/[0.06] dark:bg-ink dark:hover:border-deep-violet/20"
            >
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-sky-100 dark:bg-sky-500/10">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5 text-sky-600 dark:text-sky-400">
                  <rect x="2" y="4" width="20" height="16" rx="2" />
                  <path d="M22 7l-8.97 5.7a1.94 1.94 0 01-2.06 0L2 7" />
                </svg>
              </div>
              <div className="flex-1">
                <p className="text-[13px] font-semibold text-ink dark:text-fog">Email</p>
                <p className="text-[11px] text-ink/40 dark:text-fog/40">Receive a code at your registered business email. Instant.</p>
              </div>
              <span className="rounded-full bg-deep-violet px-3 py-1 text-[11px] font-semibold text-white">Select</span>
            </button>
          </div>

          {requesting && (
            <div className="flex items-center justify-center gap-2 py-4">
              <LogoLoader size={20} />
              <span className="text-[12px] text-ink/40 dark:text-fog/40">Requesting verification...</span>
            </div>
          )}
        </div>
      )}

      {/* Tips */}
      <div className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
        <h3 className="mb-3 text-[13px] font-semibold text-ink dark:text-fog">Why verify?</h3>
        <ul className="space-y-2">
          {[
            "Respond to reviews and Q&A from customers",
            "Add photos, posts, and business hours",
            "Appear in Google Maps and local search results",
            "Edit your business information directly",
            "Access performance insights and analytics",
          ].map((tip, i) => (
            <li key={i} className="flex items-start gap-2 text-[12px] text-ink/50 dark:text-fog/50">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500"><path d="M20 6L9 17l-5-5" /></svg>
              {tip}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
