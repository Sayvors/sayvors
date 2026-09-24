"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useAuth } from "@/lib/auth-context";
import LogoLoader from "@/components/LogoLoader";

type Mode = "login" | "signup";
type FieldName = "firstName" | "lastName" | "email" | "password" | "confirm";

interface FormValues {
  firstName: string;
  lastName: string;
  email: string;
  password: string;
  confirm: string;
  businessType: string;
  referral: string;
  newsletter: boolean;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const businessTypes = [
  "Food & Restaurant", "Cafe & Bakery", "Retail & Shops", "E-commerce",
  "Pharmacy", "Bank / Finance", "AI / SaaS / Software", "Agency",
  "Healthcare & Clinics", "Beauty & Salon", "Gym & Fitness", "Education",
  "Media / Content", "Professional Services", "Non-profit", "Other",
];

const referralOptions = [
  "Google search", "Twitter / X", "LinkedIn", "YouTube",
  "Reddit", "Friend / Colleague", "Product Hunt", "Other",
];

const defaultValues: FormValues = {
  firstName: "", lastName: "", email: "", password: "", confirm: "",
  businessType: "", referral: "", newsletter: true,
};

function strength(pw: string) {
  if (!pw) return { n: 0, label: "", color: "" };
  let n = 0;
  if (pw.length >= 8) n++;
  if (pw.length >= 12) n++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) n++;
  if (/\d/.test(pw)) n++;
  if (/[^a-zA-Z0-9]/.test(pw)) n++;
  if (n <= 2) return { n, label: "Weak", color: "bg-coral" };
  if (n <= 3) return { n, label: "Fair", color: "bg-amber-400" };
  return { n, label: "Strong", color: "bg-emerald-500" };
}

function validate(step: number, v: FormValues, isLogin: boolean) {
  const e: Partial<Record<FieldName, string>> = {};
  if (isLogin || step === 0) {
    if (!isLogin && !v.firstName.trim()) e.firstName = "Required";
    if (!isLogin && v.firstName.trim().length > 0 && v.firstName.trim().length < 2) e.firstName = "Too short";
    if (!isLogin && !v.lastName.trim()) e.lastName = "Required";
    if (!isLogin && v.lastName.trim().length > 0 && v.lastName.trim().length < 2) e.lastName = "Too short";
    if (!v.email.trim()) e.email = "Required";
    else if (!EMAIL_RE.test(v.email.trim())) e.email = "Invalid email";
  }
  if (isLogin || step === 1) {
    if (!v.password) e.password = "Required";
    else if (v.password.length < 8) e.password = "Min 8 characters";
    else if (!isLogin && !/[a-zA-Z]/.test(v.password)) e.password = "Need a letter";
    else if (!isLogin && !/\d/.test(v.password)) e.password = "Need a number";
    if (!isLogin) {
      if (!v.confirm) e.confirm = "Required";
      else if (v.confirm !== v.password) e.confirm = "No match";
    }
  }
  return e;
}

/* ── icons ─────────────────────────────────────────── */

function Eye({ open }: { open: boolean }) {
  return open ? (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ) : (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.242 4.242L9.88 9.88" />
    </svg>
  );
}

/* ── field ─────────────────────────────────────────── */

function Input({
  id, label, type = "text", value, error, placeholder, autoComplete,
  toggle, toggleVisible, onToggle, onChange, autoFocus,
}: {
  id: string; label: string; type?: string; value: string; error?: string;
  placeholder: string; autoComplete?: string; toggle?: boolean;
  toggleVisible?: boolean; onToggle?: () => void; onChange: (v: string) => void;
  autoFocus?: boolean;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium text-ink/70">{label}</label>
      <div className="relative">
        <input
          id={id} name={id}
          type={toggle && toggleVisible ? "text" : type}
          value={value} placeholder={placeholder} autoComplete={autoComplete}
          aria-invalid={!!error}
          autoFocus={autoFocus}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onChange={(e) => onChange(e.target.value)}
          className={`h-11 w-full rounded-lg border bg-white px-3.5 text-[14px] text-ink outline-none transition-all duration-200 placeholder:text-ink/35 ${
            error
              ? "border-coral/50 focus:border-coral focus:ring-[3px] focus:ring-coral/10"
              : focused
                ? "border-deep-violet/40 ring-[3px] ring-deep-violet/[0.08]"
                : "border-ink/[0.12] hover:border-ink/20"
          } ${toggle ? "pr-11" : ""}`}
        />
        {toggle && (
          <button type="button" tabIndex={-1} onClick={onToggle}
            aria-label={toggleVisible ? "Hide" : "Show"}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-ink/35 transition-colors duration-150 hover:text-ink/60">
            <Eye open={toggleVisible ?? false} />
          </button>
        )}
      </div>
      {error && (
        <p className="text-[12px] font-medium text-coral animate-in fade-in slide-in-from-top-1 duration-200">{error}</p>
      )}
    </div>
  );
}

/* ── select ────────────────────────────────────────── */

function Select({
  id, label, value, options, placeholder, onChange,
}: {
  id: string; label: string; value: string; options: string[];
  placeholder: string; onChange: (v: string) => void;
}) {
  const [focused, setFocused] = useState(false);
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium text-ink/70">{label}</label>
      <select
        id={id} value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className={`h-11 w-full appearance-none rounded-lg border bg-white px-3.5 text-[14px] text-ink outline-none transition-all duration-200 ${
          focused
            ? "border-deep-violet/40 ring-[3px] ring-deep-violet/[0.08]"
            : "border-ink/[0.12] hover:border-ink/20"
        }`}
      >
        <option value="">{placeholder}</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}

/* ── main component ────────────────────────────────── */

export default function AuthForm({ mode }: { mode: Mode }) {
  const { signup, login, googleLogin } = useAuth();
  const router = useRouter();
  const isLogin = mode === "login";
  const [step, setStep] = useState(0);
  const [v, setV] = useState<FormValues>(defaultValues);
  const [errs, setErrs] = useState<Partial<Record<FieldName, string>>>({});
  const [pwVisible, setPwVisible] = useState(false);
  const [confirmVisible, setConfirmVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loginFailed, setLoginFailed] = useState(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const [gisFailed, setGisFailed] = useState(false);

  useEffect(() => {
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
    if (!clientId) return;
    const w = window as any;
    const init = () => {
      try {
        w.google.accounts.id.initialize({
          client_id: clientId,
          callback: async ({ credential }: { credential: string }) => {
            try {
              const u = await googleLogin(credential);
              window.location.href = u?.onboarded ? "/dashboard" : "/onboarding";
            } catch {
              setNote("Google sign-in failed. Try again or use your password.");
            }
          },
        });
        if (googleBtnRef.current) {
          w.google.accounts.id.renderButton(googleBtnRef.current, {
            theme: "outline",
            size: "large",
            text: "continue_with",
            width: Math.min(googleBtnRef.current.offsetWidth || 360, 400),
          });
        }
      } catch (e) {
        console.error("Google Identity Services failed to initialize:", e);
        setGisFailed(true);
      }
    };
    if (w.google?.accounts?.id) {
      init();
      return;
    }
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.onload = init;
    s.onerror = (e) => {
      console.error("Failed to load https://accounts.google.com/gsi/client", e);
      setGisFailed(true);
    };
    document.head.appendChild(s);
    // Init once on mount; googleLogin identity is stable enough for this use.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pw = useMemo(() => strength(v.password), [v.password]);
  const totalSteps = 3;
  const stepTitle = ["Create your account", "Secure your account", "Almost done"];
  const stepSub = ["A few details to get started.", "Pick a strong password.", "Totally optional — skip if you like."];

  const set = useCallback((f: FieldName) => (val: string) => {
    setV((p) => ({ ...p, [f]: val }));
    setErrs((p) => ({ ...p, [f]: undefined }));
    setError("");
    setLoginFailed(false);
  }, []);

  const next = useCallback(() => {
    const e = validate(step, v, false);
    setErrs(e);
    if (Object.keys(e).length > 0) return;
    setStep((s) => Math.min(s + 1, totalSteps - 1));
  }, [step, v]);

  const back = useCallback(() => { setErrs({}); setStep((s) => Math.max(s - 1, 0)); }, []);

  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setError("");

    if (isLogin) {
      const e = validate(0, v, true);
      setErrs(e);
      if (Object.keys(e).length > 0) return;

      setBusy(true);
      setLoginFailed(false);
      try {
        await login({ email: v.email.trim(), password: v.password });
        setDone(true);
      } catch (err: any) {
        if (err.code === "email_not_verified") {
          router.push(`/verify-otp?email=${encodeURIComponent(v.email.trim())}`);
          return;
        }
        setError(err.message || "Login failed");
        if ((err.message || "") === "Invalid email or password") setLoginFailed(true);
      } finally {
        setBusy(false);
      }
    } else if (step < totalSteps - 1) {
      next();
      return;
    } else {
      setBusy(true);
      try {
        const result = await signup({
          first_name: v.firstName.trim(),
          last_name: v.lastName.trim(),
          email: v.email.trim(),
          password: v.password,
          business_type: v.businessType || undefined,
          referral: v.referral || undefined,
          newsletter: v.newsletter,
        });
        if (result.verification_token) {
          localStorage.setItem("verification_token", result.verification_token);
        }
        setDone(true);
      } catch (err: any) {
        setError(err.message || "Signup failed");
      } finally {
        setBusy(false);
      }
    }
  };

  /* ── success ── */
  if (done) {
    return (
      <div className="flex flex-col items-center text-center">
        <div className="relative mb-6">
          <div className="flex h-[52px] w-[52px] items-center justify-center rounded-full bg-emerald-500 transition-transform duration-300 scale-100">
            <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6"><path d="M4.5 12.75l6 6 9-13.5" /></svg>
          </div>
        </div>
        <h2 className="text-lg font-semibold text-ink">{isLogin ? "Welcome back" : "Check your email"}</h2>
        <p className="mt-1.5 text-[13px] text-ink/55">
          {isLogin ? "Redirecting you to dashboard..." : "We sent a 6-digit verification code. Enter it to activate your account."}
        </p>
        <div className="mt-7 flex w-full flex-col gap-2.5">
          {isLogin ? (
            <Link href="/dashboard" className="flex h-11 items-center justify-center rounded-lg bg-ink text-[14px] font-medium text-white transition-all duration-200 hover:bg-ink/90 active:scale-[0.98]">
              Go to dashboard
            </Link>
          ) : (
            <Link href={`/verify-otp?email=${encodeURIComponent(v.email.trim())}`} className="flex h-11 items-center justify-center rounded-lg bg-ink text-[14px] font-medium text-white transition-all duration-200 hover:bg-ink/90 active:scale-[0.98]">
              Enter verification code
            </Link>
          )}
          <button type="button" onClick={() => { setV(defaultValues); setDone(false); setStep(0); }}
            className="flex h-11 items-center justify-center rounded-lg border border-ink/[0.12] text-[14px] font-medium text-ink/60 transition-all duration-200 hover:bg-ink/[0.03] hover:border-ink/20 active:scale-[0.98]">
            Back to {isLogin ? "sign in" : "sign up"}
          </button>
        </div>
      </div>
    );
  }

  /* ── form ── */
  return (
    <>
      {/* header */}
      <div className="mb-8">
        <Link href="/" aria-label="Sayvors home" className="mb-6 inline-flex items-center gap-2">
          <Image src="/Sayvors_Icon.png" alt="" width={36} height={26} className="h-6 w-auto" />
          <Image src="/Sayvors_Wordmark_Light.png" alt="Sayvors" width={130} height={22} className="h-[22px] w-auto" priority />
        </Link>
        <h1 className="text-[22px] font-semibold tracking-tight text-ink">
          {isLogin ? "Sign in" : stepTitle[step]}
        </h1>
        <p className="mt-1.5 text-[14px] text-ink/55">
          {isLogin ? "Welcome back — enter your email to continue." : stepSub[step]}
        </p>
      </div>

      {/* step indicator */}
      {!isLogin && (
        <div className="mb-6 flex gap-2">
          {Array.from({ length: totalSteps }, (_, i) => (
            <div key={i} className="flex-1">
              <div className="relative h-[3px] overflow-hidden rounded-full bg-ink/[0.08]">
                <div
                  className={`absolute inset-y-0 left-0 rounded-full transition-all duration-500 ease-out ${
                    i < step ? "bg-ink w-full" : i === step ? "bg-ink w-full" : "w-0"
                  }`}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* social buttons */}
      <div className="space-y-2.5">
        {!gisFailed && process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID && (
          <div ref={googleBtnRef} className="min-h-11 w-full [&>div]:!w-full" />
        )}
        <button type="button" onClick={() => setNote("GitHub sign-in coming soon.")}
          className="flex h-11 w-full items-center justify-center gap-2.5 rounded-lg border border-ink/[0.12] text-[14px] font-medium text-ink/70 transition-all duration-200 hover:border-ink/20 hover:bg-ink/[0.02] active:scale-[0.99]">
          <Image src="/github.svg" alt="" width={18} height={18} className="h-[18px] w-[18px]" />
          Continue with GitHub
        </button>
      </div>
      {note && (
        <div className="mt-3 rounded-lg bg-coral/[0.07] px-3 py-2.5 text-center text-[12px] font-medium text-coral animate-in fade-in duration-200">{note}</div>
      )}

      {/* divider */}
      <div className="my-5 flex items-center gap-3">
        <span className="h-px flex-1 bg-ink/[0.07]" />
        <span className="text-[11px] font-medium uppercase tracking-widest text-ink/35">or</span>
        <span className="h-px flex-1 bg-ink/[0.07]" />
      </div>

      <form onSubmit={submit} noValidate className="space-y-3.5">
        {/* step 0 — name + email */}
        {!isLogin && step === 0 && (
          <>
            <div className="flex gap-3">
              <div className="flex-1">
                <Input id="firstName" label="First name" value={v.firstName} error={errs.firstName}
                  placeholder="Ada" autoComplete="given-name" onChange={set("firstName")} autoFocus />
              </div>
              <div className="flex-1">
                <Input id="lastName" label="Last name" value={v.lastName} error={errs.lastName}
                  placeholder="Lovelace" autoComplete="family-name" onChange={set("lastName")} />
              </div>
            </div>
            <Input id="email" label="Email" type="email" value={v.email} error={errs.email}
              placeholder="you@company.com" autoComplete="email" onChange={set("email")} />
          </>
        )}

        {/* step 1 — password */}
        {!isLogin && step === 1 && (
          <>
            <Input id="password" label="Password" type="password" value={v.password} error={errs.password}
              placeholder="Min. 8 characters" autoComplete="new-password" toggle
              toggleVisible={pwVisible} onToggle={() => setPwVisible((p) => !p)} onChange={set("password")} autoFocus />
            {v.password.length > 0 && (
              <div className="flex items-center gap-2.5 pt-0.5">
                <div className="flex flex-1 gap-1">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className={`h-[3px] flex-1 rounded-full transition-all duration-300 ${i <= pw.n ? pw.color : "bg-ink/[0.06]"}`} />
                  ))}
                </div>
                <span className={`text-[11px] font-medium transition-colors duration-200 ${pw.n <= 2 ? "text-coral" : pw.n <= 3 ? "text-amber-500" : "text-emerald-600"}`}>{pw.label}</span>
              </div>
            )}
            <Input id="confirm" label="Confirm password" type="password" value={v.confirm} error={errs.confirm}
              placeholder="Re-enter password" autoComplete="new-password" toggle
              toggleVisible={confirmVisible} onToggle={() => setConfirmVisible((p) => !p)} onChange={set("confirm")} />
          </>
        )}

        {/* step 2 — optional details */}
        {!isLogin && step === 2 && (
          <>
            <Select id="businessType" label="What do you do?" value={v.businessType}
              options={businessTypes} placeholder="Select — optional" onChange={(val) => setV((p) => ({ ...p, businessType: val }))} />
            <Select id="referral" label="How did you find us?" value={v.referral}
              options={referralOptions} placeholder="Select — optional" onChange={(val) => setV((p) => ({ ...p, referral: val }))} />
            <label className="flex items-start gap-3 pt-1">
              <input type="checkbox" checked={v.newsletter}
                onChange={(e) => setV((p) => ({ ...p, newsletter: e.target.checked }))}
                className="mt-0.5 h-4 w-4 rounded border-ink/20 accent-deep-violet" />
              <span className="text-[13px] leading-snug text-ink/60">Send me product updates. Unsubscribe anytime.</span>
            </label>
          </>
        )}

        {/* login fields */}
        {isLogin && (
          <>
            <Input id="email" label="Email" type="email" value={v.email} error={errs.email}
              placeholder="you@company.com" autoComplete="email" onChange={set("email")} autoFocus />
            <div>
              <Input id="password" label="Password" type="password" value={v.password} error={errs.password}
                placeholder="Your password" autoComplete="current-password" toggle
                toggleVisible={pwVisible} onToggle={() => setPwVisible((p) => !p)} onChange={set("password")} />
              <div className="mt-2 flex justify-end">
                <a href="/forgot-password" className="text-[12px] font-medium text-ink/45 transition-colors duration-150 hover:text-ink/60">Forgot password?</a>
              </div>
            </div>
          </>
        )}

        {/* actions */}
        <div className="flex gap-2.5 pt-1.5">
          {!isLogin && step > 0 && (
            <button type="button" onClick={back}
              className="h-11 px-4 rounded-lg border border-ink/[0.12] text-[13px] font-medium text-ink/55 transition-all duration-200 hover:border-ink/20 hover:text-ink/70 active:scale-[0.98]">
              Back
            </button>
          )}
          <button type="submit" disabled={busy}
            className="h-11 flex-1 rounded-lg bg-ink text-[14px] font-medium text-white transition-all duration-200 hover:bg-ink/90 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed">
            {busy ? (
              <span className="inline-flex items-center gap-2"><LogoLoader size={18} /> {isLogin ? "Signing in..." : "Creating..."}</span>
            ) : isLogin ? "Sign in" : step === totalSteps - 1 ? "Create account" : "Continue"}
          </button>
        </div>
        {error && <p className="mt-3 text-center text-[12px] font-medium text-coral animate-in fade-in duration-200">{error}</p>}
        {isLogin && loginFailed && (
          <p className="mt-2 text-center text-[12px] text-ink/55 animate-in fade-in duration-200">
            New here?{" "}
            <Link href="/signup" className="font-medium text-ink/70 underline underline-offset-2 transition-colors duration-150 hover:text-ink">Create an account</Link>
            {" "}— you can Continue with Google.
          </p>
        )}
      </form>

      {/* footer links */}
      {isLogin && (
        <p className="mt-6 text-center text-[13px] text-ink/50">
          Don{"\u2019"}t have an account?{" "}
          <Link href="/signup" className="font-medium text-ink/70 transition-colors duration-150 hover:text-ink">Sign up</Link>
        </p>
      )}
      {!isLogin && step === 0 && (
        <p className="mt-5 text-center text-[13px] text-ink/50">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-ink/70 transition-colors duration-150 hover:text-ink">Sign in</Link>
        </p>
      )}
      {!isLogin && step === 2 && (
        <p className="mt-5 text-center text-[11px] text-ink/40">
          By continuing you agree to our{" "}
          <a href="#" className="underline underline-offset-2 hover:text-ink/55">Terms</a> and{" "}
          <a href="#" className="underline underline-offset-2 hover:text-ink/55">Privacy Policy</a>.
        </p>
      )}
    </>
  );
}
