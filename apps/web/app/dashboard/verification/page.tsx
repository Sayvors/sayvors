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
  attempts: number;
}

type Step = "pick" | "phone-enter" | "phone-otp" | "sms-enter" | "sms-otp" |
  "email-enter" | "email-otp" | "postcard-confirm" | "postcard-pending" |
  "video-intro" | "video-upload" | "video-pending" |
  "live-intro" | "live-schedule" | "live-pending";

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
  const [step, setStep] = useState<Step>("pick");
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Form state
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [submitting, setSubmitting] = useState(false);

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
          location_id: selectedId!, verified: false, pending: false,
          method: null, verified_at: null, attempts: 0,
        });
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  const reset = () => { setStep("pick"); setPhone(""); setEmail(""); setOtp(""); };

  const submitPhone = async () => {
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/verification`, {
        method: "POST", body: JSON.stringify({ method: "phone", phone }),
      });
      setStep("phone-otp");
    } catch { setBanner({ kind: "err", text: "Could not send code." }); }
    setSubmitting(false);
  };

  const submitSms = async () => {
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/verification`, {
        method: "POST", body: JSON.stringify({ method: "sms", phone }),
      });
      setStep("sms-otp");
    } catch { setBanner({ kind: "err", text: "Could not send code." }); }
    setSubmitting(false);
  };

  const submitEmail = async () => {
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/verification`, {
        method: "POST", body: JSON.stringify({ method: "email", email }),
      });
      setStep("email-otp");
    } catch { setBanner({ kind: "err", text: "Could not send code." }); }
    setSubmitting(false);
  };

  const submitOtp = async (method: string) => {
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/verification/confirm`, {
        method: "POST", body: JSON.stringify({ method, code: otp }),
      });
      setStatus((prev) => prev ? { ...prev, verified: true, verified_at: new Date().toISOString() } : null);
      setBanner({ kind: "ok", text: "Verified!" });
      reset();
    } catch { setBanner({ kind: "err", text: "Invalid code." }); }
    setSubmitting(false);
  };

  const submitPostcard = async () => {
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/verification`, {
        method: "POST", body: JSON.stringify({ method: "postcard" }),
      });
      setStep("postcard-pending");
      setStatus((prev) => prev ? { ...prev, pending: true, method: "postcard" } : null);
    } catch { setBanner({ kind: "err", text: "Could not request postcard." }); }
    setSubmitting(false);
  };

  const submitVideo = async () => {
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/verification`, {
        method: "POST", body: JSON.stringify({ method: "video" }),
      });
      setStep("video-pending");
      setStatus((prev) => prev ? { ...prev, pending: true, method: "video" } : null);
    } catch { setBanner({ kind: "err", text: "Could not submit video." }); }
    setSubmitting(false);
  };

  const submitLive = async () => {
    setSubmitting(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/verification`, {
        method: "POST", body: JSON.stringify({ method: "live_video" }),
      });
      setStep("live-pending");
      setStatus((prev) => prev ? { ...prev, pending: true, method: "live_video" } : null);
    } catch { setBanner({ kind: "err", text: "Could not schedule call." }); }
    setSubmitting(false);
  };

  if (loading) return <div className="flex h-full items-center justify-center"><LogoLoader size={32} /></div>;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5 max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Verification</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Verify your Google Business Profile.</p>
        </div>
        <div className="relative">
          <select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value)}
            className="w-56 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog">
            {locations.map((loc) => <option key={loc.id} value={loc.id}>{loc.name}</option>)}
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

      {/* Breadcrumb */}
      {step !== "pick" && (
        <div className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
          <button onClick={reset} className="hover:text-ink dark:hover:text-fog">Methods</button>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          <span className="font-medium text-ink dark:text-fog">{stepLabel(step)}</span>
        </div>
      )}

      {/* Status Card */}
      {(status?.verified || status?.pending) && step === "pick" && (
        <div className={`rounded-2xl border p-5 ${status.verified ? "border-emerald-200 bg-emerald-50 dark:border-emerald-500/20 dark:bg-emerald-500/[0.06]" : "border-amber-200 bg-amber-50 dark:border-amber-500/20 dark:bg-amber-500/[0.06]"}`}>
          <div className="flex items-center gap-3">
            {status.verified ? (
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-500/10">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-5 w-5 text-emerald-600 dark:text-emerald-400"><path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" /></svg>
              </div>
            ) : (
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-500/10">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 text-amber-600 dark:text-amber-400"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
              </div>
            )}
            <div>
              <p className="text-[14px] font-semibold text-ink dark:text-fog">{status.verified ? "Verified" : "Pending"}</p>
              <p className="text-[11px] text-ink/40 dark:text-fog/40">
                {status.verified ? `Verified${status.verified_at ? ` on ${new Date(status.verified_at).toLocaleDateString()}` : ""}` : `Via ${status.method} — waiting for confirmation`}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── Step: Pick Method ── */}
      {step === "pick" && (
        <div className="grid gap-3 sm:grid-cols-2">
          <MethodCard icon={<MailIcon />} color="violet" title="Postcard" desc="Mail to your business address" badge="5–14 days" onClick={() => setStep("postcard-confirm")} />
          <MethodCard icon={<PhoneIcon />} color="emerald" title="Phone Call" desc="Automated call with code" badge="Instant" onClick={() => setStep("phone-enter")} />
          <MethodCard icon={<SmsIcon />} color="sky" title="SMS" desc="Text message with code" badge="Instant" onClick={() => setStep("sms-enter")} />
          <MethodCard icon={<EmailIcon />} color="violet" title="Email" desc="Code sent to business email" badge="Instant" onClick={() => setStep("email-enter")} />
          <MethodCard icon={<VideoIcon />} color="amber" title="Video" desc="Record your business location" badge="1–3 days" onClick={() => setStep("video-intro")} />
          <MethodCard icon={<LiveCallIcon />} color="rose" title="Live Call" desc="Video call with Google agent" badge="Schedule" onClick={() => setStep("live-intro")} />
        </div>
      )}

      {/* ── Phone Enter ── */}
      {step === "phone-enter" && (
        <FlowCard title="Phone Verification" desc="Enter your business phone number. We'll call with a code.">
          <Field label="Phone Number">
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+966 55 000 0000" className="input-field" autoFocus />
          </Field>
          <FlowActions onBack={reset} onConfirm={submitPhone} disabled={!phone.trim() || submitting} confirmLabel="Call Me" loading={submitting} />
        </FlowCard>
      )}

      {/* ── Phone OTP ── */}
      {step === "phone-otp" && (
        <FlowCard title="Enter Code" desc="Enter the 6-digit code from the phone call.">
          <Field label="Verification Code">
            <input value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="000000" maxLength={6} className="input-field text-center text-[20px] tracking-[0.3em] font-mono" autoFocus />
          </Field>
          <FlowActions onBack={() => setStep("phone-enter")} onConfirm={() => submitOtp("phone")} disabled={otp.length !== 6 || submitting} confirmLabel="Verify" loading={submitting} />
        </FlowCard>
      )}

      {/* ── SMS Enter ── */}
      {step === "sms-enter" && (
        <FlowCard title="SMS Verification" desc="Enter your business phone number. We'll text a code.">
          <Field label="Phone Number">
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+966 55 000 0000" className="input-field" autoFocus />
          </Field>
          <FlowActions onBack={reset} onConfirm={submitSms} disabled={!phone.trim() || submitting} confirmLabel="Send SMS" loading={submitting} />
        </FlowCard>
      )}

      {/* ── SMS OTP ── */}
      {step === "sms-otp" && (
        <FlowCard title="Enter Code" desc="Enter the 6-digit code from the text message.">
          <Field label="Verification Code">
            <input value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="000000" maxLength={6} className="input-field text-center text-[20px] tracking-[0.3em] font-mono" autoFocus />
          </Field>
          <FlowActions onBack={() => setStep("sms-enter")} onConfirm={() => submitOtp("sms")} disabled={otp.length !== 6 || submitting} confirmLabel="Verify" loading={submitting} />
        </FlowCard>
      )}

      {/* ── Email Enter ── */}
      {step === "email-enter" && (
        <FlowCard title="Email Verification" desc="Enter your business email address.">
          <Field label="Email Address">
            <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@business.com" className="input-field" autoFocus />
          </Field>
          <FlowActions onBack={reset} onConfirm={submitEmail} disabled={!email.trim() || submitting} confirmLabel="Send Code" loading={submitting} />
        </FlowCard>
      )}

      {/* ── Email OTP ── */}
      {step === "email-otp" && (
        <FlowCard title="Enter Code" desc="Enter the 6-digit code from your email.">
          <Field label="Verification Code">
            <input value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="000000" maxLength={6} className="input-field text-center text-[20px] tracking-[0.3em] font-mono" autoFocus />
          </Field>
          <FlowActions onBack={() => setStep("email-enter")} onConfirm={() => submitOtp("email")} disabled={otp.length !== 6 || submitting} confirmLabel="Verify" loading={submitting} />
        </FlowCard>
      )}

      {/* ── Postcard Confirm ── */}
      {step === "postcard-confirm" && (
        <FlowCard title="Postcard Verification" desc="We'll mail a postcard with a verification code to your business address.">
          <div className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
            <p className="text-[12px] font-medium text-ink/50 dark:text-fog/50">Mailing address</p>
            <p className="mt-1 text-[13px] text-ink dark:text-fog">{locations.find((l) => l.id === selectedId)?.address ?? "No address set"}</p>
          </div>
          <p className="text-[11px] text-ink/35 dark:text-fog/35">Delivery takes 5–14 business days. You'll enter the code once it arrives.</p>
          <FlowActions onBack={reset} onConfirm={submitPostcard} disabled={submitting} confirmLabel="Send Postcard" loading={submitting} />
        </FlowCard>
      )}

      {/* ── Postcard Pending ── */}
      {step === "postcard-pending" && (
        <FlowCard title="Postcard Sent" desc="Your postcard is on the way.">
          <PendingState icon={<MailIcon />} text="Arrives in 5–14 business days. Enter the code when it arrives." />
          <FlowActions onBack={reset} confirmLabel="Back to Methods" onConfirm={reset} />
        </FlowCard>
      )}

      {/* ── Video Intro ── */}
      {step === "video-intro" && (
        <FlowCard title="Video Verification" desc="Record a short video showing your business location.">
          <div className="space-y-2">
            {["Show the exterior with business signage visible", "Walk inside and show the business interior", "Show products, equipment, or services in action", "Keep video under 2 minutes"].map((tip, i) => (
              <div key={i} className="flex items-start gap-2 text-[12px] text-ink/50 dark:text-fog/50">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500"><path d="M20 6L9 17l-5-5" /></svg>
                {tip}
              </div>
            ))}
          </div>
          <FlowActions onBack={reset} onConfirm={() => setStep("video-upload")} confirmLabel="Continue" />
        </FlowCard>
      )}

      {/* ── Video Upload ── */}
      {step === "video-upload" && (
        <FlowCard title="Upload Video" desc="Select or record your verification video.">
          <div className="flex flex-col items-center rounded-xl border-2 border-dashed border-ink/[0.12] bg-ink/[0.02] py-10 dark:border-fog/[0.12] dark:bg-fog/[0.02]">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="mb-2 h-8 w-8 text-ink/20 dark:text-fog/20">
              <polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
            </svg>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">Drag and drop or click to browse</p>
            <p className="text-[10px] text-ink/25 dark:text-fog/25">MP4, MOV up to 100MB</p>
          </div>
          <FlowActions onBack={() => setStep("video-intro")} onConfirm={submitVideo} disabled={submitting} confirmLabel="Submit Video" loading={submitting} />
        </FlowCard>
      )}

      {/* ── Video Pending ── */}
      {step === "video-pending" && (
        <FlowCard title="Video Submitted" desc="Your video is under review.">
          <PendingState icon={<VideoIcon />} text="Google typically reviews within 1–3 business days. We'll notify you of the result." />
          <FlowActions onBack={reset} confirmLabel="Back to Methods" onConfirm={reset} />
        </FlowCard>
      )}

      {/* ── Live Call Intro ── */}
      {step === "live-intro" && (
        <FlowCard title="Live Video Call" desc="Join a live video call with a Google agent to verify your location.">
          <div className="space-y-2">
            {["A Google agent will guide you through the call", "Show your business signage and interior", "Have your business documents ready", "Call takes approximately 5–10 minutes"].map((tip, i) => (
              <div key={i} className="flex items-start gap-2 text-[12px] text-ink/50 dark:text-fog/50">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-500"><path d="M20 6L9 17l-5-5" /></svg>
                {tip}
              </div>
            ))}
          </div>
          <FlowActions onBack={reset} onConfirm={() => setStep("live-schedule")} confirmLabel="Schedule Call" />
        </FlowCard>
      )}

      {/* ── Live Schedule ── */}
      {step === "live-schedule" && (
        <FlowCard title="Schedule Call" desc="Pick a date and time for your verification call.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Date">
              <input type="date" className="input-field" />
            </Field>
            <Field label="Time">
              <input type="time" className="input-field" />
            </Field>
          </div>
          <FlowActions onBack={() => setStep("live-intro")} onConfirm={submitLive} disabled={submitting} confirmLabel="Confirm Schedule" loading={submitting} />
        </FlowCard>
      )}

      {/* ── Live Pending ── */}
      {step === "live-pending" && (
        <FlowCard title="Call Scheduled" desc="Your verification call is booked.">
          <PendingState icon={<LiveCallIcon />} text="Check your email for calendar invite and call details." />
          <FlowActions onBack={reset} confirmLabel="Back to Methods" onConfirm={reset} />
        </FlowCard>
      )}
    </div>
  );
}

/* ── Shared Components ──────────────────────────── */

function MethodCard({ icon, color, title, desc, badge, onClick }: {
  icon: React.ReactNode; color: string; title: string; desc: string; badge: string; onClick: () => void;
}) {
  const colors: Record<string, { bg: string; ring: string }> = {
    violet: { bg: "bg-deep-violet/10", ring: "hover:ring-deep-violet/20" },
    emerald: { bg: "bg-emerald-100 dark:bg-emerald-500/10", ring: "hover:ring-emerald-300" },
    sky: { bg: "bg-sky-100 dark:bg-sky-500/10", ring: "hover:ring-sky-300" },
    amber: { bg: "bg-amber-100 dark:bg-amber-500/10", ring: "hover:ring-amber-300" },
    rose: { bg: "bg-rose-100 dark:bg-rose-500/10", ring: "hover:ring-rose-300" },
  };
  const c = colors[color] ?? colors.violet;
  return (
    <button onClick={onClick}
      className={`group flex flex-col items-center gap-3 rounded-2xl border border-ink/[0.06] bg-white p-5 text-center transition hover:border-transparent hover:shadow-lg hover:ring-2 ${c.ring} dark:border-fog/[0.06] dark:bg-ink`}>
      <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${c.bg} transition group-hover:scale-105`}>
        {icon}
      </div>
      <div>
        <p className="text-[13px] font-semibold text-ink dark:text-fog">{title}</p>
        <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">{desc}</p>
      </div>
      <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[10px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">{badge}</span>
    </button>
  );
}

function FlowCard({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-ink/[0.06] bg-white p-6 dark:border-fog/[0.06] dark:bg-ink">
      <h2 className="text-[16px] font-bold text-ink dark:text-fog">{title}</h2>
      <p className="mt-1 text-[12px] text-ink/40 dark:text-fog/40">{desc}</p>
      <div className="mt-5 space-y-4">{children}</div>
    </div>
  );
}

function FlowActions({ onBack, onConfirm, disabled, confirmLabel, loading }: {
  onBack: () => void; onConfirm: () => void; disabled?: boolean; confirmLabel: string; loading?: boolean;
}) {
  return (
    <div className="flex items-center justify-between pt-2">
      <button onClick={onBack} className="text-[12px] font-medium text-ink/40 hover:text-ink dark:text-fog/40 dark:hover:text-fog">Back</button>
      <button onClick={onConfirm} disabled={disabled}
        className="rounded-xl bg-deep-violet px-5 py-2 text-[13px] font-semibold text-white transition hover:opacity-90 disabled:opacity-50">
        {loading ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> </span> : confirmLabel}
      </button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-ink/50 dark:text-fog/50">{label}</label>
      {children}
    </div>
  );
}

function PendingState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 dark:border-amber-500/20 dark:bg-amber-500/[0.06]">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-100 text-amber-600 dark:bg-amber-500/10 dark:text-amber-400">
        {icon}
      </div>
      <p className="text-[12px] text-amber-700 dark:text-amber-300">{text}</p>
    </div>
  );
}

function stepLabel(step: Step): string {
  const labels: Record<string, string> = {
    "phone-enter": "Phone", "phone-otp": "Phone Code",
    "sms-enter": "SMS", "sms-otp": "SMS Code",
    "email-enter": "Email", "email-otp": "Email Code",
    "postcard-confirm": "Postcard", "postcard-pending": "Postcard Sent",
    "video-intro": "Video", "video-upload": "Upload Video", "video-pending": "Video Submitted",
    "live-intro": "Live Call", "live-schedule": "Schedule", "live-pending": "Call Scheduled",
  };
  return labels[step] ?? step;
}

/* ── Icons ──────────────────────────────────────── */

function MailIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" /></svg>;
}
function PhoneIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" /></svg>;
}
function SmsIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" /><path d="M8 10h8M8 14h4" /></svg>;
}
function EmailIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M22 7l-8.97 5.7a1.94 1.94 0 01-2.06 0L2 7" /></svg>;
}
function VideoIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><polygon points="23 7 16 12 23 17 23 7" /><rect x="1" y="5" width="15" height="14" rx="2" ry="2" /></svg>;
}
function LiveCallIcon() {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5"><path d="M15.6 11.6L22 7v10l-6.4-4.5" /><rect x="2" y="7" width="15" height="10" rx="2" /><circle cx="9.5" cy="12" r="1" fill="currentColor" /></svg>;
}
