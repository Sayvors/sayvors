"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AdminGuard from "@/components/admin/AdminGuard";
import LogoLoader from "@/components/LogoLoader";
import {
  adminLogout,
  createPlan,
  getSubscription,
  getTenantEntitlements,
  grantPlan,
  listPlanFeatures,
  listPlans,
  searchTenants,
  updatePlan,
  type AdminEntitlements,
  type AdminPlan,
  type AdminSubscription,
  type AdminTenant,
  type PlanFeatureSpec,
} from "@/lib/api-admin";

function fmtCents(c: number): string {
  return `$${(c / 100).toFixed(c % 100 === 0 ? 0 : 2)}`;
}

const EMPTY_FORM = {
  slug: "",
  name: "",
  description: "",
  priceDollars: "",
  creditDollars: "",
  maxChannels: "",
  maxMessages: "",
  is_active: true,
  sort_order: "0",
};

function PlanEditor({
  plan,
  catalog,
  onSaved,
  onCancel,
}: {
  plan: AdminPlan | null;
  catalog: PlanFeatureSpec[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const isNew = plan === null;
  const [form, setForm] = useState(() =>
    plan
      ? {
          slug: plan.slug,
          name: plan.name,
          description: plan.description ?? "",
          priceDollars: String(plan.price_cents / 100),
          creditDollars: String(plan.included_credit_cents / 100),
          maxChannels: plan.max_channels == null ? "" : String(plan.max_channels),
          maxMessages:
            plan.max_messages_per_month == null ? "" : String(plan.max_messages_per_month),
          is_active: plan.is_active,
          sort_order: String(plan.sort_order),
        }
      : { ...EMPTY_FORM },
  );
  const [features, setFeatures] = useState<Record<string, boolean>>(plan?.features ?? {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (k: string, v: string | boolean) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    if (busy) return;
    if (!form.slug.trim() || !form.name.trim()) {
      setError("Slug and name are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        ...(isNew ? { slug: form.slug.trim() } : {}),
        name: form.name.trim(),
        description: form.description.trim() || null,
        price_cents: Math.max(0, Math.round(Number(form.priceDollars || 0) * 100)),
        included_credit_cents: Math.max(0, Math.round(Number(form.creditDollars || 0) * 100)),
        max_channels: form.maxChannels === "" ? null : Math.max(1, Number(form.maxChannels)),
        max_messages_per_month:
          form.maxMessages === "" ? null : Math.max(1, Number(form.maxMessages)),
        features,
        is_active: form.is_active,
        sort_order: Number(form.sort_order || 0),
      };
      if (isNew) await createPlan(body);
      else await updatePlan(plan.id, body);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-[24px] bg-white p-5 shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_18px_36px_-20px_rgba(20,16,31,0.35)] dark:bg-ink">
      <h3 className="text-[15px] font-bold">{isNew ? "New plan" : `Edit ${plan.name}`}</h3>
      {error && (
        <p role="alert" className="mt-3 rounded-2xl bg-[#FF4F6E]/10 px-4 py-3 text-[12px] font-medium text-[#C4304B] dark:text-[#FF8FA3]">
          {error}
        </p>
      )}
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[12px] font-semibold">Slug {isNew ? "" : "(locked)"}</span>
          <input value={form.slug} disabled={!isNew} onChange={(e) => set("slug", e.target.value)} className="input-field h-10 w-full disabled:opacity-50" placeholder="pro" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-semibold">Name</span>
          <input value={form.name} onChange={(e) => set("name", e.target.value)} className="input-field h-10 w-full" placeholder="Pro" />
        </label>
        <label className="block sm:col-span-2">
          <span className="mb-1 block text-[12px] font-semibold">Description</span>
          <input value={form.description} onChange={(e) => set("description", e.target.value)} className="input-field h-10 w-full" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-semibold">Price (USD / month)</span>
          <input value={form.priceDollars} onChange={(e) => set("priceDollars", e.target.value)} inputMode="decimal" className="input-field h-10 w-full" placeholder="0" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-semibold">Included AI credit (USD)</span>
          <input value={form.creditDollars} onChange={(e) => set("creditDollars", e.target.value)} inputMode="decimal" className="input-field h-10 w-full" placeholder="0" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-semibold">Max channels (blank = unlimited)</span>
          <input value={form.maxChannels} onChange={(e) => set("maxChannels", e.target.value)} inputMode="numeric" className="input-field h-10 w-full" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-semibold">Max messages / month (blank = unlimited)</span>
          <input value={form.maxMessages} onChange={(e) => set("maxMessages", e.target.value)} inputMode="numeric" className="input-field h-10 w-full" />
        </label>
        <label className="block">
          <span className="mb-1 block text-[12px] font-semibold">Sort order</span>
          <input value={form.sort_order} onChange={(e) => set("sort_order", e.target.value)} inputMode="numeric" className="input-field h-10 w-full" />
        </label>
        <label className="flex items-center gap-2 pt-6 text-[13px] font-semibold">
          <input type="checkbox" checked={form.is_active} onChange={(e) => set("is_active", e.target.checked)} className="h-4 w-4 accent-[#3D1D6E]" />
          Active (visible to tenants)
        </label>
      </div>
      <h4 className="mb-2 mt-5 text-[12px] font-bold uppercase tracking-[0.12em] text-ink/45 dark:text-fog/45">
        Features — checked means included
      </h4>
      <div className="grid gap-1.5 sm:grid-cols-2">
        {catalog.map((f) => (
          <label
            key={f.key}
            title={f.description}
            className="flex cursor-pointer items-start gap-2.5 rounded-2xl border border-ink/[0.07] px-3 py-2.5 transition hover:border-ink/20 dark:border-fog/10 dark:hover:border-fog/25"
          >
            <input
              type="checkbox"
              checked={!!features[f.key]}
              onChange={(e) => setFeatures((prev) => ({ ...prev, [f.key]: e.target.checked }))}
              className="mt-0.5 h-4 w-4 shrink-0 accent-[#3D1D6E]"
            />
            <span>
              <span className="block text-[13px] font-semibold leading-4">{f.label}</span>
              <span className="mt-0.5 block text-[11px] leading-4 text-ink/50 dark:text-fog/50">{f.description}</span>
            </span>
          </label>
        ))}
      </div>
      <div className="mt-5 flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="h-11 rounded-[20px] bg-deep-violet px-6 text-[13px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] disabled:opacity-40 focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
        >
          {busy ? "Saving…" : isNew ? "Create plan" : "Save changes"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-11 rounded-[20px] border border-ink/10 px-5 text-[13px] font-bold text-ink/70 transition hover:bg-ink/[0.04] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/15 dark:text-fog/70 dark:hover:bg-fog/[0.06]"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function TenantPanel({ plans, onChanged }: { plans: AdminPlan[]; onChanged: () => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AdminTenant[]>([]);
  const [searching, setSearching] = useState(false);
  const [tenant, setTenant] = useState<AdminTenant | null>(null);
  const [sub, setSub] = useState<AdminSubscription | null>(null);
  const [ent, setEnt] = useState<AdminEntitlements | null>(null);
  const [grantSlug, setGrantSlug] = useState("");
  const [grantUntil, setGrantUntil] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const r = await searchTenants(query.trim());
        setResults(r.items);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  const selectTenant = async (t: AdminTenant) => {
    setTenant(t);
    setSub(null);
    setEnt(null);
    setNotice(null);
    setError(null);
    try {
      const [s, e] = await Promise.all([
        getSubscription(t.id).catch(() => null),
        getTenantEntitlements(t.id),
      ]);
      setSub(s);
      setEnt(e);
      setGrantSlug(s?.plan_slug ?? e.plan_slug);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load tenant.");
    }
  };

  const doGrant = async () => {
    if (!tenant || !grantSlug || busy) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const s = await grantPlan(tenant.id, grantSlug, grantUntil || null);
      setSub(s);
      const e = await getTenantEntitlements(tenant.id);
      setEnt(e);
      setNotice(`Plan set to ${s.plan_name ?? grantSlug}.`);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Grant failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-[24px] bg-white p-5 shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_18px_36px_-20px_rgba(20,16,31,0.35)] dark:bg-ink">
      <h3 className="text-[15px] font-bold">Assign plan to tenant</h3>
      <div className="mt-3 flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by email…"
          aria-label="Search tenants by email"
          className="input-field h-10 flex-1"
        />
        {searching && <span className="self-center text-[12px] text-ink/40">…</span>}
      </div>
      {results.length > 0 && (
        <ul className="mt-2 divide-y divide-ink/[0.06] rounded-2xl border border-ink/[0.07] dark:divide-fog/10 dark:border-fog/10">
          {results.map((t) => (
            <li key={t.id}>
              <button
                type="button"
                onClick={() => selectTenant(t)}
                className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[13px] transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.04] ${tenant?.id === t.id ? "bg-deep-violet/[0.06]" : ""}`}
              >
                <span className="min-w-0">
                  <span className="block truncate font-semibold">{t.email}</span>
                  <span className="block truncate text-[11px] text-ink/45 dark:text-fog/45">
                    {[t.first_name, t.last_name].filter(Boolean).join(" ") || "—"} · {t.plan}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="mt-3 rounded-2xl bg-[#FF4F6E]/10 px-4 py-3 text-[12px] font-medium text-[#C4304B] dark:text-[#FF8FA3]">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="mt-3 rounded-2xl bg-emerald-500/10 px-4 py-3 text-[12px] font-medium text-emerald-700 dark:text-emerald-300">
          {notice}
        </p>
      )}
      {tenant && ent && (
        <div className="mt-4 rounded-2xl border border-ink/[0.07] p-4 dark:border-fog/10">
          <p className="text-[13px] font-bold">{tenant.email}</p>
          <p className="mt-0.5 text-[12px] text-ink/55 dark:text-fog/55">
            Effective plan: <strong>{ent.plan_name}</strong> ({ent.status})
            {ent.promo_active && ent.granted_until
              ? ` · promo until ${new Date(ent.granted_until).toLocaleDateString()}`
              : ""}
            {sub?.granted_by ? ` · by ${sub.granted_by}` : ""}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {Object.entries(ent.features)
              .filter(([, v]) => v)
              .map(([k]) => (
                <span key={k} className="rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-emerald-700 dark:text-emerald-300">
                  {k}
                </span>
              ))}
            {Object.values(ent.features).every((v) => !v) && (
              <span className="text-[12px] text-ink/45">No features enabled.</span>
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="block min-w-40 flex-1">
              <span className="mb-1 block text-[12px] font-semibold">Plan</span>
              <select value={grantSlug} onChange={(e) => setGrantSlug(e.target.value)} className="input-field h-10 w-full">
                {plans.filter((p) => p.is_active).map((p) => (
                  <option key={p.id} value={p.slug}>{p.name} ({p.slug})</option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] font-semibold">Promo until (optional)</span>
              <input type="datetime-local" value={grantUntil} onChange={(e) => setGrantUntil(e.target.value)} className="input-field h-10" />
            </label>
            <button
              type="button"
              onClick={doGrant}
              disabled={busy || !grantSlug}
              className="h-10 rounded-[18px] bg-deep-violet px-5 text-[13px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] disabled:opacity-40 focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
            >
              {busy ? "Saving…" : "Assign plan"}
            </button>
          </div>
          <p className="mt-2 text-[11px] text-ink/45 dark:text-fog/45">
            An empty promo date assigns the plan as the base subscription. A future date grants it as a time-limited promo, then it drops back automatically.
          </p>
        </div>
      )}
    </div>
  );
}

export default function AdminPlansPage() {
  const router = useRouter();
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [catalog, setCatalog] = useState<PlanFeatureSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<AdminPlan | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([listPlans(), listPlanFeatures()]);
      setPlans(p);
      setCatalog(c);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load plans.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sorted = useMemo(
    () => [...plans].sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
    [plans],
  );

  const toggleActive = async (plan: AdminPlan) => {
    setToggling(plan.id);
    try {
      await updatePlan(plan.id, { is_active: !plan.is_active });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed.");
    } finally {
      setToggling(null);
    }
  };

  const logout = async () => {
    const { adminLogout } = await import("@/lib/api-admin");
    await adminLogout();
    router.replace("/admin/login");
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LogoLoader />
      </div>
    );
  }

  return (
    <AdminGuard>
      <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-ink/40 dark:text-fog/40">
              Platform admin
            </p>
            <h1 className="mt-1 text-[24px] font-extrabold tracking-tight">Plans &amp; tenants</h1>
            <p className="mt-1 text-[13px] text-ink/55 dark:text-fog/55">
              Edit what each plan includes, and assign plans to tenants. Changes apply on the next request — no deploy.
            </p>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setEditing("new")}
              className="h-10 rounded-[18px] bg-deep-violet px-5 text-[13px] font-bold text-white transition active:translate-y-[2px] active:scale-[0.98] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet"
            >
              New plan
            </button>
            <button
              type="button"
              onClick={logout}
              className="h-10 rounded-[18px] border border-ink/10 px-4 text-[13px] font-bold text-ink/60 transition hover:bg-ink/[0.04] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-deep-violet dark:border-fog/15 dark:text-fog/60 dark:hover:bg-fog/[0.06]"
            >
              Sign out
            </button>
          </div>
        </header>

        {error && (
          <p role="alert" className="mb-4 rounded-2xl bg-[#FF4F6E]/10 px-4 py-3 text-[12px] font-medium text-[#C4304B] dark:text-[#FF8FA3]">
            {error}
          </p>
        )}

        {editing !== null && (
          <div className="mb-4">
            <PlanEditor
              plan={editing === "new" ? null : editing}
              catalog={catalog}
              onSaved={() => {
                setEditing(null);
                void load();
              }}
              onCancel={() => setEditing(null)}
            />
          </div>
        )}

        <div className="overflow-hidden rounded-[24px] bg-white shadow-[0_1px_0_rgba(255,255,255,0.9)_inset,0_18px_36px_-20px_rgba(20,16,31,0.35)] dark:bg-ink">
          <table className="w-full text-left text-[13px]">
            <thead>
              <tr className="border-b border-ink/[0.07] text-[11px] uppercase tracking-[0.1em] text-ink/45 dark:border-fog/10 dark:text-fog/45">
                <th className="px-4 py-3 font-bold">Plan</th>
                <th className="px-4 py-3 font-bold">Price</th>
                <th className="px-4 py-3 font-bold">Limits</th>
                <th className="px-4 py-3 font-bold">Features on</th>
                <th className="px-4 py-3 font-bold">Status</th>
                <th className="px-4 py-3 font-bold"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink/[0.06] dark:divide-fog/10">
              {sorted.map((p) => {
                const on = Object.entries(p.features ?? {}).filter(([, v]) => v).length;
                return (
                  <tr key={p.id} className={!p.is_active ? "opacity-55" : ""}>
                    <td className="px-4 py-3">
                      <span className="block font-bold">{p.name}</span>
                      <span className="block text-[11px] text-ink/45 dark:text-fog/45">{p.slug}</span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3">{fmtCents(p.price_cents)}/mo</td>
                    <td className="px-4 py-3 text-[12px] text-ink/60 dark:text-fog/60">
                      {p.max_channels == null ? "∞ channels" : `${p.max_channels} channels`}
                      {" · "}
                      {p.max_messages_per_month == null ? "∞ msgs" : `${p.max_messages_per_month} msgs/mo`}
                    </td>
                    <td className="px-4 py-3 text-[12px]">{on} on</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${p.is_active ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300" : "bg-ink/[0.06] text-ink/50 dark:bg-fog/10 dark:text-fog/50"}`}>
                        {p.is_active ? "Active" : "Off"}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => setEditing(p)}
                        className="mr-2 rounded-full px-3 py-1 text-[12px] font-bold text-deep-violet transition hover:bg-deep-violet/10 focus-visible:outline-[3px] focus-visible:outline-deep-violet"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => toggleActive(p)}
                        disabled={toggling === p.id}
                        className="rounded-full px-3 py-1 text-[12px] font-bold text-ink/60 transition hover:bg-ink/[0.05] disabled:opacity-40 focus-visible:outline-[3px] focus-visible:outline-deep-violet dark:text-fog/60"
                      >
                        {p.is_active ? "Disable" : "Enable"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="mt-4">
          <TenantPanel plans={plans} onChanged={load} />
        </div>
      </div>
    </AdminGuard>
  );
}
