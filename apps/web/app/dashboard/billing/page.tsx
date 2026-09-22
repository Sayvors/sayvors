"use client";

import { useEffect, useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import LogoLoader from "@/components/LogoLoader";
import { getProfile } from "@/lib/api-profile";
import {
  addPaymentMethod,
  getBillingProfile,
  getBudget,
  listPaymentMethods,
  removePaymentMethod,
  saveBillingProfile,
  setDefaultMethod,
  type BillingProfile,
  type Budget,
  type PaymentMethod,
} from "@/lib/api-billing";

const inputCls =
  "w-full rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 disabled:opacity-50 dark:border-fog/[0.1] dark:bg-ink dark:text-fog";

function fieldInput(hasError: boolean): string {
  return hasError
    ? `${inputCls} border-coral/70 focus:border-coral`
    : inputCls;
}

function Field({ label, hint, required, error, children }: { label: string; hint?: string; required?: boolean; error?: string | null; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-ink/60 dark:text-fog/60">
        {label}
        {required && <span className="ml-0.5 font-bold text-coral">*</span>}
        {hint && <span className="ml-1.5 font-normal text-ink/40 dark:text-fog/40">{hint}</span>}
      </label>
      {children}
      {error && <p className="mt-1 text-[11px] font-medium text-coral">{error}</p>}
    </div>
  );
}

function Section({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
      <h2 className="text-[15px] font-bold text-ink dark:text-fog">{title}</h2>
      <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">{subtitle}</p>
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  );
}

// ── Card brand detection (BIN ranges, runs locally in the browser) ──

function detectBrand(digits: string): string {
  if (digits.length < 2) return "unknown";
  if (/^(4576|5888|6361|6054)/.test(digits)) return "mada";
  if (/^3[47]/.test(digits)) return "amex";
  if (/^(51|52|53|54|55)/.test(digits)) return "mastercard";
  if (/^2(?:22[1-9]|2[3-9]|[3-6]\d|7[01]|720)/.test(digits)) return "mastercard";
  if (/^4/.test(digits)) return "visa";
  if (/^6(?:011|5)/.test(digits)) return "discover";
  if (/^62/.test(digits)) return "unionpay";
  return digits.length >= 6 ? "other" : "unknown";
}

function luhnValid(digits: string): boolean {
  if (digits.length < 13 || digits.length > 19) return false;
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let d = Number(digits[i]);
    if (alt) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
    alt = !alt;
  }
  return sum % 10 === 0;
}

const BRAND_GRADIENT: Record<string, string> = {
  visa: "from-[#1A1F71] to-[#3B4BD8]",
  mastercard: "from-[#EB001B] to-[#F79E1B]",
  amex: "from-[#2E77BC] to-[#5EB3E4]",
  mada: "from-[#007A53] to-[#00A651]",
  discover: "from-[#F48120] to-[#B85C00]",
  unionpay: "from-[#DE1F26] to-[#007D8A]",
  applepay: "from-[#2A2440] to-[#6D28D9]",
  other: "from-[#2A2440] to-[#6D28D9]",
  unknown: "from-[#2A2440] to-[#6D28D9]",
};

function brandGradient(brand: string): string {
  return BRAND_GRADIENT[brand.toLowerCase()] ?? BRAND_GRADIENT.other;
}

const BRAND_LABEL: Record<string, string> = {
  visa: "VISA",
  mastercard: "Mastercard",
  amex: "AMEX",
  mada: "mada",
  discover: "Discover",
  unionpay: "UnionPay",
  applepay: "Apple Pay",
};

function brandLabel(brand: string): string {
  return BRAND_LABEL[brand.toLowerCase()] ?? (brand.slice(0, 8).toUpperCase() || "Card");
}

function formatCardGroups(digits: string): string {
  const padded = (digits + "•".repeat(16)).slice(0, 16);
  return padded.replace(/(.{4})/g, "$1 ").trim();
}

function formatExpiryInput(v: string): string {
  const d = v.replace(/[^0-9]/g, "").slice(0, 4);
  if (d.length <= 2) return d;
  return `${d.slice(0, 2)}/${d.slice(2)}`;
}

function expiryError(v: string): string | null {
  const d = v.replace(/[^0-9]/g, "");
  if (d.length < 4) return "Use MM/YY.";
  const mm = Number(d.slice(0, 2));
  const yy = Number(d.slice(2, 4));
  if (mm < 1 || mm > 12) return "Month must be 01–12.";
  const now = new Date();
  const lastDay = new Date(2000 + yy, mm, 0);
  if (lastDay.getTime() < now.getTime()) return "This card is expired.";
  if (2000 + yy > now.getFullYear() + 15) return "That year looks too far ahead.";
  return null;
}

function parseExpiry(v: string): { month: number; year: number } {
  const d = v.replace(/[^0-9]/g, "");
  return { month: Number(d.slice(0, 2)), year: 2000 + Number(d.slice(2, 4)) };
}

function CardPreview({ brand, digits, holder, expiry }: { brand: string; digits: string; holder: string; expiry: string }) {
  return (
    <div className={`relative overflow-hidden rounded-2xl bg-gradient-to-br p-4 text-white shadow-lg ${brandGradient(brand)}`}>
      <div className="pointer-events-none absolute -right-10 -top-10 h-36 w-36 rounded-full bg-white/10" aria-hidden />
      <div className="pointer-events-none absolute -bottom-14 -left-6 h-40 w-40 rounded-full bg-black/10" aria-hidden />
      <div className="relative flex items-start justify-between">
        <div className="flex h-8 w-11 items-center justify-center rounded-md bg-white/25" aria-hidden>
          <div className="h-4 w-6 rounded-[3px] border border-white/50" />
        </div>
        <span className="text-[15px] font-black tracking-wide">{brandLabel(brand)}</span>
      </div>
      <p className="relative mt-4 text-[16px] font-semibold tabular-nums tracking-[0.08em]">
        {formatCardGroups(digits)}
      </p>
      <div className="relative mt-3 flex items-end justify-between gap-2">
        <p className="truncate text-[11px] font-medium uppercase tracking-wide text-white/85">
          {holder.trim() || "YOUR NAME"}
        </p>
        <p className="shrink-0 text-[11px] font-semibold tabular-nums text-white/85">
          {expiry.replace(/[^0-9/]/g, "") || "MM/YY"}
        </p>
      </div>
    </div>
  );
}

const EMPTY_PROFILE: BillingProfile = {
  id: "",
  user_id: "",
  full_name: null,
  email: null,
  phone: null,
  address_line1: null,
  address_line2: null,
  city: null,
  region: null,
  postal_code: null,
  country: null,
  tax_id: null,
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const COUNTRIES: { code: string; name: string }[] = [
  { code: "SA", name: "Saudi Arabia" },
  { code: "AE", name: "United Arab Emirates" },
  { code: "US", name: "United States" },
  { code: "GB", name: "United Kingdom" },
  { code: "CA", name: "Canada" },
  { code: "AU", name: "Australia" },
  { code: "DE", name: "Germany" },
  { code: "FR", name: "France" },
  { code: "EG", name: "Egypt" },
  { code: "JO", name: "Jordan" },
  { code: "KW", name: "Kuwait" },
  { code: "QA", name: "Qatar" },
  { code: "BH", name: "Bahrain" },
  { code: "OM", name: "Oman" },
  { code: "IQ", name: "Iraq" },
  { code: "LB", name: "Lebanon" },
  { code: "TR", name: "Turkey" },
  { code: "IN", name: "India" },
  { code: "PK", name: "Pakistan" },
  { code: "BD", name: "Bangladesh" },
  { code: "MY", name: "Malaysia" },
  { code: "SG", name: "Singapore" },
  { code: "ID", name: "Indonesia" },
  { code: "PH", name: "Philippines" },
  { code: "TH", name: "Thailand" },
  { code: "JP", name: "Japan" },
  { code: "KR", name: "South Korea" },
  { code: "CN", name: "China" },
  { code: "IT", name: "Italy" },
  { code: "ES", name: "Spain" },
  { code: "NL", name: "Netherlands" },
  { code: "SE", name: "Sweden" },
  { code: "NO", name: "Norway" },
  { code: "DK", name: "Denmark" },
  { code: "FI", name: "Finland" },
  { code: "BE", name: "Belgium" },
  { code: "CH", name: "Switzerland" },
  { code: "AT", name: "Austria" },
  { code: "IE", name: "Ireland" },
  { code: "PT", name: "Portugal" },
  { code: "GR", name: "Greece" },
  { code: "PL", name: "Poland" },
  { code: "CZ", name: "Czech Republic" },
  { code: "RO", name: "Romania" },
  { code: "RU", name: "Russia" },
  { code: "UA", name: "Ukraine" },
  { code: "IL", name: "Israel" },
  { code: "MA", name: "Morocco" },
  { code: "DZ", name: "Algeria" },
  { code: "TN", name: "Tunisia" },
  { code: "LY", name: "Libya" },
  { code: "SD", name: "Sudan" },
  { code: "YE", name: "Yemen" },
  { code: "SY", name: "Syria" },
  { code: "ZA", name: "South Africa" },
  { code: "NG", name: "Nigeria" },
  { code: "KE", name: "Kenya" },
  { code: "GH", name: "Ghana" },
  { code: "BR", name: "Brazil" },
  { code: "MX", name: "Mexico" },
  { code: "AR", name: "Argentina" },
  { code: "CL", name: "Chile" },
  { code: "CO", name: "Colombia" },
  { code: "NZ", name: "New Zealand" },
  { code: "OTHER", name: "Other" },
];

export default function BillingPage() {
  const [plan, setPlan] = useState("free");
  const [budget, setBudget] = useState<Budget | null>(null);
  const [profile, setProfile] = useState<BillingProfile>(EMPTY_PROFILE);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  // Add-card form (full PAN never leaves the browser — only last4 is saved)
  const [cardNumber, setCardNumber] = useState("");
  const [expiry, setExpiry] = useState("");
  const [holder, setHolder] = useState("");
  const [makeDefault, setMakeDefault] = useState(false);
  const [cardTouched, setCardTouched] = useState(false);

  // Billing details (trimmed to the essentials)
  const [detailsTouched, setDetailsTouched] = useState(false);
  const [authEmail, setAuthEmail] = useState("");

  const digits = cardNumber.replace(/[^0-9]/g, "");
  const detected = detectBrand(digits);

  const numberError: string | null =
    digits.length === 0
      ? null
      : digits.length < 13
        ? `Too short — card numbers have 13–19 digits (${digits.length} typed).`
        : !luhnValid(digits)
          ? "This number doesn't pass the checksum — check and retry."
          : null;
  const expiryErr = expiry ? expiryError(expiry) : null;
  const holderError: string | null =
    holder === "" ? null : holder.trim().length < 2 ? "Enter the name printed on the card." : null;

  const nameError: string | null =
    (profile.full_name ?? "").trim() === "" ? "Full name is required." : null;
  const emailError: string | null =
    authEmail.trim() === ""
      ? "Your sign-in email is missing — re-login."
      : !EMAIL_RE.test(authEmail.trim())
        ? "That email doesn't look valid."
        : null;
  const countryVal = (profile.country ?? "").trim().toUpperCase();
  const countryError: string | null =
    countryVal === "" ? "Country is required." : null;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [prof, profBilling, meths, wallet] = await Promise.all([
          getProfile().catch(() => null),
          getBillingProfile().catch(() => null),
          listPaymentMethods().catch(() => []),
          getBudget().catch(() => null),
        ]);
        if (cancelled) return;
        if (wallet) {
          setBudget(wallet);
          setPlan(wallet.plan);
        } else if (prof?.plan) setPlan(prof.plan);
        const signedInEmail = prof?.email ?? "";
        setAuthEmail(signedInEmail);
        if (profBilling) {
          setProfile({ ...profBilling, email: signedInEmail || profBilling.email });
        } else {
          setProfile({ ...EMPTY_PROFILE, email: signedInEmail });
        }
        setMethods(Array.isArray(meths) ? meths : []);
      } catch {
        /* empty states render */
      }
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const set = (patch: Partial<BillingProfile>) =>
    setProfile((p) => ({ ...p, ...patch }));

  async function saveDetails() {
    setDetailsTouched(true);
    if (nameError || emailError || countryError) {
      setBanner({ kind: "err", text: "Fix the highlighted billing fields first." });
      return;
    }
    setBusy("profile");
    setBanner(null);
    try {
      // Unmanaged fields (phone, address…) ride along untouched so nothing is wiped.
      const updated = await saveBillingProfile({
        full_name: (profile.full_name ?? "").trim() || null,
        email: authEmail.trim() || null,
        phone: profile.phone || null,
        address_line1: profile.address_line1 || null,
        address_line2: profile.address_line2 || null,
        city: (profile.city ?? "").trim() || null,
        region: profile.region || null,
        postal_code: profile.postal_code || null,
        country: countryVal || null,
        tax_id: (profile.tax_id ?? "").trim() || null,
      });
      setProfile(updated);
      setDetailsTouched(false);
      setBanner({ kind: "ok", text: "Billing details saved." });
    } catch (e) {
      setBanner({ kind: "err", text: e instanceof Error ? e.message.slice(0, 200) : "Could not save." });
    } finally {
      setBusy(null);
    }
  }

  async function handleAddCard() {
    setCardTouched(true);
    const numErr =
      digits.length === 0
        ? "Enter the card number."
        : digits.length < 13
          ? "Card numbers have 13–19 digits."
          : !luhnValid(digits)
            ? "This number doesn't pass the checksum — check and retry."
            : null;
    const expErr = expiry === "" ? "Enter the expiry." : expiryError(expiry);
    const holdErr = holder.trim().length < 2 ? "Enter the name printed on the card." : null;
    if (numErr || expErr || holdErr) {
      setBanner({ kind: "err", text: numErr ?? expErr ?? holdErr ?? "Check the card fields." });
      return;
    }
    const { month, year } = parseExpiry(expiry);
    const brand = detected === "unknown" ? "other" : detected;
    setBusy("add");
    setBanner(null);
    try {
      const created = await addPaymentMethod({
        brand,
        last4: digits.slice(-4),
        exp_month: month,
        exp_year: year,
        holder_name: holder.trim(),
        is_default: makeDefault || methods.length === 0,
      });
      setMethods((prev) => {
        const next = [created, ...prev.filter((m) => m.id !== created.id)];
        return created.is_default
          ? next.map((m) => (m.id === created.id ? m : { ...m, is_default: false }))
          : next;
      });
      setCardNumber("");
      setExpiry("");
      setHolder("");
      setMakeDefault(false);
      setCardTouched(false);
      setBanner({ kind: "ok", text: "Card saved — only the last 4 digits were sent. Gateway verification lands soon." });
    } catch (e) {
      setBanner({ kind: "err", text: e instanceof Error ? e.message.slice(0, 200) : "Could not save card." });
    } finally {
      setBusy(null);
    }
  }

  async function handleSetDefault(id: string) {
    setBusy(`default-${id}`);
    try {
      const updated = await setDefaultMethod(id);
      setMethods((prev) => prev.map((m) => (m.id === id ? updated : { ...m, is_default: false })));
    } catch {
      /* badge corrects on reload */
    } finally {
      setBusy(null);
    }
  }

  async function handleRemove(id: string) {
    setBusy(`remove-${id}`);
    setConfirmDelete(null);
    try {
      await removePaymentMethod(id);
      const remaining = methods.filter((m) => m.id !== id);
      const wasDefault = methods.find((m) => m.id === id)?.is_default;
      setMethods(
        wasDefault && remaining.length > 0
          ? remaining.map((m, i) => (i === 0 ? { ...m, is_default: true } : m))
          : remaining
      );
    } catch {
      /* list corrects on reload */
    } finally {
      setBusy(null);
    }
  }

  const lowBalance = budget !== null && budget.balance_cents < 200;

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Billing" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Billing</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
          Plan, billing details and saved cards. Card numbers are never stored — only brand, last digits and expiry.
        </p>
      </div>

      {banner && (
        <div
          role="status"
          className={`rounded-xl border p-3 text-[13px] ${
            banner.kind === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-red-200 bg-red-50 text-red-600"
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span>{banner.text}</span>
            <button className="shrink-0 text-[12px] underline underline-offset-2" onClick={() => setBanner(null)}>
              dismiss
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16">
          <LogoLoader size={28} />
        </div>
      ) : (
        <>
          <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-deep-violet via-[#4C1D95] to-ink p-5 text-white shadow-lg sm:p-6">
            <div className="pointer-events-none absolute -right-12 -top-12 h-44 w-44 rounded-full bg-white/10" aria-hidden />
            <div className="pointer-events-none absolute -bottom-16 -left-8 h-48 w-48 rounded-full bg-black/20" aria-hidden />
            <div className="relative flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/60">Current plan</p>
                <p className="mt-1 text-[30px] font-black capitalize leading-none">{plan}</p>
                <p className="mt-2 max-w-md text-[12px] text-white/70">
                  {plan === "pro"
                    ? "Pro includes a $20 AI credit wallet — every AI reply, analysis and chat message spends from it."
                    : "Free has no AI credits — upgrade to Pro to unlock AI replies, analyses and chat."}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-white/60">AI credits left</p>
                <p className="mt-1 text-[30px] font-black tabular-nums leading-none">
                  {budget ? `$${budget.balance_dollars.toFixed(2)}` : "—"}
                </p>
                {lowBalance ? (
                  <p className="mt-2 text-[12px] font-bold text-amber-300">
                    Balance is low — contact support to top up.
                  </p>
                ) : (
                  <p className="mt-2 text-[12px] text-white/70">Top-ups arrive with subscriptions.</p>
                )}
              </div>
            </div>
          </div>

          <Section title="Billing details" subtitle="Only the essentials — used on invoices and receipts.">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Full name" required error={detailsTouched ? nameError : null}>
                <input value={profile.full_name ?? ""} onChange={(e) => set({ full_name: e.target.value })} disabled={busy !== null} placeholder="Sara Ahmed" className={fieldInput(detailsTouched && !!nameError)} />
              </Field>
              <Field label="Billing email" required hint="your sign-in email" error={detailsTouched ? emailError : null}>
                <input value={authEmail} disabled placeholder="you@example.com" inputMode="email" readOnly className={`${inputCls} cursor-not-allowed opacity-70`} />
              </Field>
              <Field label="Country" required error={detailsTouched ? countryError : null}>
                <select
                  value={countryVal}
                  onChange={(e) => set({ country: e.target.value })}
                  disabled={busy !== null}
                  className={fieldInput(detailsTouched && !!countryError)}
                >
                  <option value="">Select country…</option>
                  {COUNTRIES.map((c) => (
                    <option key={c.code} value={c.code}>{c.name}</option>
                  ))}
                </select>
              </Field>
              <Field label="City">
                <input value={profile.city ?? ""} onChange={(e) => set({ city: e.target.value })} disabled={busy !== null} placeholder="Riyadh" className={inputCls} />
              </Field>
              <div className="sm:col-span-2">
                <Field label="Business tax ID (optional)" hint="VAT/GST number for company invoices — leave blank if none">
                  <input value={profile.tax_id ?? ""} onChange={(e) => set({ tax_id: e.target.value })} disabled={busy !== null} placeholder="e.g. 300123456700003" className={inputCls} />
                </Field>
              </div>
            </div>
            <p className="text-[11px] text-ink/40 dark:text-fog/40"><span className="font-bold text-coral">*</span> required</p>
            <button
              onClick={() => void saveDetails()}
              disabled={busy !== null}
              className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
            >
              {busy === "profile" ? "Saving…" : "Save billing details"}
            </button>
          </Section>

          <Section title="Payment methods" subtitle="Saved cards for future charges. Only brand, last digits and expiry are kept.">
            {methods.length === 0 ? (
              <p className="rounded-lg bg-ink/[0.03] px-3 py-3 text-[12px] text-ink/50 dark:bg-fog/[0.04] dark:text-fog/50">
                No cards yet — add one below. Cards save as unverified records until gateway verification lands.
              </p>
            ) : (
              <ul className="space-y-2">
                {methods.map((m) => (
                  <li key={m.id} className="flex items-stretch gap-0 overflow-hidden rounded-xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
                    <div className={`flex w-24 shrink-0 flex-col justify-between bg-gradient-to-br p-2.5 text-white ${brandGradient(m.brand)}`}>
                      <span className="text-[11px] font-black tracking-wide">{brandLabel(m.brand)}</span>
                      <span className="text-[10px] font-semibold tabular-nums text-white/85">
                        {String(m.exp_month).padStart(2, "0")}/{m.exp_year}
                      </span>
                    </div>
                    <div className="min-w-0 flex-1 px-3.5 py-3">
                      <p className="flex flex-wrap items-center gap-2 text-[14px] font-bold tabular-nums tracking-[0.06em] text-ink dark:text-fog">
                        •••• {m.last4}
                        {m.is_default && (
                          <span className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-bold tracking-normal text-deep-violet">★ Default</span>
                        )}
                        {!m.verified && (
                          <span title="Gateway verification lands soon" className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold tracking-normal text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                            Unverified
                          </span>
                        )}
                      </p>
                      <p className="mt-0.5 truncate text-[11px] text-ink/45 dark:text-fog/45">
                        {m.holder_name ?? "No holder name"}
                        {m.expired && <span className="ml-1.5 font-bold text-coral">· Expired</span>}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5 px-2.5">
                      {!m.is_default && (
                        <button
                          onClick={() => void handleSetDefault(m.id)}
                          disabled={busy !== null}
                          className="rounded-lg px-2 py-1 text-[11px] font-semibold text-deep-violet outline-none transition hover:bg-deep-violet/[0.06] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-40"
                        >
                          {busy === `default-${m.id}` ? "…" : "Set default"}
                        </button>
                      )}
                      {confirmDelete === m.id ? (
                        <>
                          <button
                            onClick={() => void handleRemove(m.id)}
                            disabled={busy !== null}
                            className="rounded-lg bg-red-600 px-2 py-1 text-[11px] font-bold text-white disabled:opacity-40"
                          >
                            Confirm
                          </button>
                          <button onClick={() => setConfirmDelete(null)} className="rounded-lg px-2 py-1 text-[11px] font-semibold text-ink/50">
                            Keep
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => setConfirmDelete(m.id)}
                          disabled={busy !== null}
                          className="rounded-lg px-2 py-1 text-[11px] font-semibold text-red-500 outline-none transition hover:bg-red-500/10 focus-visible:ring-2 focus-visible:ring-red-500/40 disabled:opacity-40"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <div className="rounded-xl border border-dashed border-ink/[0.1] p-4 dark:border-fog/[0.1]">
              <h3 className="text-[13px] font-bold text-ink dark:text-fog">Add a card</h3>
              <p className="mt-0.5 text-[11px] text-ink/45 dark:text-fog/45">
                Type the number — the brand is detected automatically and only the last 4 digits are ever sent or stored.
              </p>
              <div className="mt-3">
                <CardPreview brand={detected} digits={digits} holder={holder} expiry={expiry} />
              </div>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <div className="sm:col-span-2">
                  <Field
                    label="Card number"
                    required
                    hint={detected !== "unknown" && detected !== "other" ? `Detected: ${brandLabel(detected)}` : undefined}
                    error={cardTouched ? numberError : null}
                  >
                    <input
                      value={cardNumber}
                      onChange={(e) => setCardNumber(e.target.value.replace(/[^0-9]/g, "").slice(0, 19).replace(/(\d{4})(?=\d)/g, "$1 "))}
                      disabled={busy !== null}
                      placeholder="4242 4242 4242 4242"
                      inputMode="numeric"
                      autoComplete="cc-number"
                      className={`${fieldInput(cardTouched && !!numberError)} tabular-nums tracking-[0.06em]`}
                    />
                  </Field>
                </div>
                <Field label="Name on card" required error={cardTouched ? holderError : null}>
                  <input value={holder} onChange={(e) => setHolder(e.target.value)} disabled={busy !== null} placeholder="SARA AHMED" autoComplete="cc-name" className={fieldInput(cardTouched && !!holderError)} />
                </Field>
                <Field label="Expiry" required hint="MM/YY" error={cardTouched ? expiryErr : null}>
                  <input
                    value={expiry}
                    onChange={(e) => setExpiry(formatExpiryInput(e.target.value))}
                    disabled={busy !== null}
                    placeholder="08/27"
                    inputMode="numeric"
                    autoComplete="cc-exp"
                    className={`${fieldInput(cardTouched && !!expiryErr)} tabular-nums`}
                  />
                </Field>
              </div>
              <label className="mt-3 flex cursor-pointer items-center gap-2 text-[12px] font-medium text-ink/60 dark:text-fog/60">
                <input type="checkbox" checked={makeDefault} onChange={(e) => setMakeDefault(e.target.checked)} disabled={busy !== null} className="h-4 w-4 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/40" />
                Make default{methods.length === 0 ? " (first card is default automatically)" : ""}
              </label>
              <button
                onClick={() => void handleAddCard()}
                disabled={busy !== null}
                className="mt-3 rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
              >
                {busy === "add" ? "Saving…" : "Save card"}
              </button>
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
