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

const BRANDS = ["visa", "mastercard", "mada", "amex", "applepay", "other"];

const BRAND_STYLE: Record<string, string> = {
  visa: "bg-[#1A1F71] text-white",
  mastercard: "bg-[#EB001B] text-white",
  mada: "bg-emerald-600 text-white",
  amex: "bg-[#2E77BC] text-white",
  applepay: "bg-ink text-white dark:bg-fog dark:text-ink",
  other: "bg-ink/[0.06] text-ink/60 dark:bg-fog/[0.08] dark:text-fog/60",
};

function brandStyle(brand: string): string {
  return BRAND_STYLE[brand.toLowerCase()] ?? BRAND_STYLE.other;
}

const inputCls =
  "w-full rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 disabled:opacity-50 dark:border-fog/[0.1] dark:bg-ink dark:text-fog";

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-ink/60 dark:text-fog/60">
        {label}
        {hint && <span className="ml-1.5 font-normal text-ink/40 dark:text-fog/40">{hint}</span>}
      </label>
      {children}
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

function thisYear(): number {
  return new Date().getFullYear();
}

export default function BillingPage() {
  const [plan, setPlan] = useState("free");
  const [budget, setBudget] = useState<Budget | null>(null);
  const [profile, setProfile] = useState<BillingProfile>(EMPTY_PROFILE);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  // Add-card form
  const [holder, setHolder] = useState("");
  const [brand, setBrand] = useState("visa");
  const [last4, setLast4] = useState("");
  const [expMonth, setExpMonth] = useState("1");
  const [expYear, setExpYear] = useState(String(thisYear() + 2));
  const [makeDefault, setMakeDefault] = useState(false);

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
        if (profBilling) setProfile(profBilling);
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
    setBusy("profile");
    setBanner(null);
    try {
      const updated = await saveBillingProfile({
        full_name: profile.full_name || null,
        email: profile.email || null,
        phone: profile.phone || null,
        address_line1: profile.address_line1 || null,
        address_line2: profile.address_line2 || null,
        city: profile.city || null,
        region: profile.region || null,
        postal_code: profile.postal_code || null,
        country: profile.country || null,
        tax_id: profile.tax_id || null,
      });
      setProfile(updated);
      setBanner({ kind: "ok", text: "Billing details saved." });
    } catch (e) {
      setBanner({ kind: "err", text: e instanceof Error ? e.message.slice(0, 200) : "Could not save." });
    } finally {
      setBusy(null);
    }
  }

  async function handleAddCard() {
    if (!/^[0-9]{4}$/.test(last4)) {
      setBanner({ kind: "err", text: "Last 4 digits must be exactly 4 numbers — we never ask for the full card number." });
      return;
    }
    setBusy("add");
    setBanner(null);
    try {
      const created = await addPaymentMethod({
        brand,
        last4,
        exp_month: Number(expMonth),
        exp_year: Number(expYear),
        holder_name: holder.trim() || undefined,
        is_default: makeDefault,
      });
      setMethods((prev) => {
        const next = [created, ...prev.filter((m) => m.id !== created.id)];
        return created.is_default
          ? next.map((m) => (m.id === created.id ? m : { ...m, is_default: false }))
          : next;
      });
      setHolder("");
      setLast4("");
      setMakeDefault(false);
      setBanner({ kind: "ok", text: "Card saved as an unverified record — gateway verification lands soon." });
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

  const years = Array.from({ length: 12 }, (_, i) => thisYear() + i);

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
          <Section title="Current plan" subtitle="Your subscription tier.">
            <div className="flex flex-wrap items-center gap-3">
              <span className="rounded-lg bg-deep-violet px-3 py-1.5 text-[13px] font-bold capitalize text-white">
                {plan}
              </span>
              <p className="text-[12px] text-ink/50 dark:text-fog/50">
                Plan changes and invoices arrive with subscriptions.
              </p>
            </div>
            <div className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.08] dark:bg-fog/[0.04]">
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[12px] font-medium text-ink/60 dark:text-fog/60">
                  AI credits remaining
                </span>
                <span className="text-[15px] font-bold text-ink dark:text-fog">
                  {budget ? `$${budget.balance_dollars.toFixed(2)}` : "—"}
                </span>
              </div>
              <p className="mt-1 text-[12px] text-ink/50 dark:text-fog/50">
                Every AI reply, analysis and chat message spends from this balance.
                When it runs out, AI features pause until you top up.
              </p>
              {budget && budget.balance_cents < 200 && (
                <p className="mt-1.5 text-[12px] font-medium text-amber-600 dark:text-amber-400">
                  Balance is low — contact support to top up your AI credits.
                </p>
              )}
            </div>
          </Section>

          <Section title="Billing details" subtitle="Used on invoices and receipts, including VAT records.">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Full name">
                <input value={profile.full_name ?? ""} onChange={(e) => set({ full_name: e.target.value })} disabled={busy !== null} placeholder="Sara Ahmed" className={inputCls} />
              </Field>
              <Field label="Billing email">
                <input value={profile.email ?? ""} onChange={(e) => set({ email: e.target.value })} disabled={busy !== null} placeholder="billing@company.com" className={inputCls} />
              </Field>
              <Field label="Phone">
                <input value={profile.phone ?? ""} onChange={(e) => set({ phone: e.target.value })} disabled={busy !== null} placeholder="+966 55 000 0000" className={inputCls} />
              </Field>
              <Field label="VAT / tax number" hint="e.g. Saudi ZATCA VAT">
                <input value={profile.tax_id ?? ""} onChange={(e) => set({ tax_id: e.target.value })} disabled={busy !== null} placeholder="300123456700003" className={inputCls} />
              </Field>
              <Field label="Address line 1">
                <input value={profile.address_line1 ?? ""} onChange={(e) => set({ address_line1: e.target.value })} disabled={busy !== null} placeholder="King Fahd Rd, Building 12" className={inputCls} />
              </Field>
              <Field label="Address line 2">
                <input value={profile.address_line2 ?? ""} onChange={(e) => set({ address_line2: e.target.value })} disabled={busy !== null} placeholder="Office 4 (optional)" className={inputCls} />
              </Field>
              <Field label="City">
                <input value={profile.city ?? ""} onChange={(e) => set({ city: e.target.value })} disabled={busy !== null} placeholder="Riyadh" className={inputCls} />
              </Field>
              <Field label="Region">
                <input value={profile.region ?? ""} onChange={(e) => set({ region: e.target.value })} disabled={busy !== null} placeholder="Riyadh Province" className={inputCls} />
              </Field>
              <Field label="Postal code">
                <input value={profile.postal_code ?? ""} onChange={(e) => set({ postal_code: e.target.value })} disabled={busy !== null} placeholder="11432" className={inputCls} />
              </Field>
              <Field label="Country" hint="ISO code">
                <input value={profile.country ?? ""} onChange={(e) => set({ country: e.target.value })} disabled={busy !== null} placeholder="SA" maxLength={8} className={inputCls} />
              </Field>
            </div>
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
                  <li key={m.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-ink/[0.06] bg-white px-3.5 py-3 dark:border-fog/[0.06] dark:bg-ink">
                    <span aria-hidden className={`flex h-9 w-14 shrink-0 items-center justify-center rounded-md text-[10px] font-black uppercase tracking-wide ${brandStyle(m.brand)}`}>
                      {m.brand.slice(0, 6)}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-bold tabular-nums text-ink dark:text-fog">
                        •••• {m.last4}
                        <span className="ml-2 font-medium text-ink/45 dark:text-fog/45">
                          {String(m.exp_month).padStart(2, "0")}/{m.exp_year}
                        </span>
                      </p>
                      <p className="truncate text-[11px] text-ink/45 dark:text-fog/45">
                        {m.holder_name ?? "No holder name"}
                        {m.expired && <span className="ml-1.5 font-bold text-coral">· Expired</span>}
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {m.is_default ? (
                        <span className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-bold text-deep-violet">Default</span>
                      ) : (
                        <button
                          onClick={() => void handleSetDefault(m.id)}
                          disabled={busy !== null}
                          className="rounded-lg px-2 py-1 text-[11px] font-semibold text-deep-violet outline-none transition hover:bg-deep-violet/[0.06] focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-40"
                        >
                          {busy === `default-${m.id}` ? "…" : "Set default"}
                        </button>
                      )}
                      {!m.verified && (
                        <span title="Gateway verification lands soon" className="rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                          Unverified
                        </span>
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
                Last digits and expiry only — never type a full card number or CVC here.
              </p>
              <div className="mt-3 grid gap-3 sm:grid-cols-2">
                <Field label="Cardholder name">
                  <input value={holder} onChange={(e) => setHolder(e.target.value)} disabled={busy !== null} placeholder="Sara Ahmed" className={inputCls} />
                </Field>
                <Field label="Brand">
                  <select value={brand} onChange={(e) => setBrand(e.target.value)} disabled={busy !== null} className={inputCls}>
                    {BRANDS.map((b) => (
                      <option key={b} value={b}>{b === "applepay" ? "Apple Pay" : b.charAt(0).toUpperCase() + b.slice(1)}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Last 4 digits" hint="exactly 4 numbers">
                  <input value={last4} onChange={(e) => setLast4(e.target.value.replace(/[^0-9]/g, "").slice(0, 4))} disabled={busy !== null} placeholder="4242" inputMode="numeric" className={`${inputCls} tabular-nums`} />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Exp. month">
                    <select value={expMonth} onChange={(e) => setExpMonth(e.target.value)} disabled={busy !== null} className={inputCls}>
                      {Array.from({ length: 12 }, (_, i) => i + 1).map((mm) => (
                        <option key={mm} value={mm}>{String(mm).padStart(2, "0")}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Exp. year">
                    <select value={expYear} onChange={(e) => setExpYear(e.target.value)} disabled={busy !== null} className={inputCls}>
                      {years.map((yy) => (
                        <option key={yy} value={yy}>{yy}</option>
                      ))}
                    </select>
                  </Field>
                </div>
              </div>
              <label className="mt-3 flex cursor-pointer items-center gap-2 text-[12px] font-medium text-ink/60 dark:text-fog/60">
                <input type="checkbox" checked={makeDefault} onChange={(e) => setMakeDefault(e.target.checked)} disabled={busy !== null} className="h-4 w-4 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/40" />
                Make default
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
