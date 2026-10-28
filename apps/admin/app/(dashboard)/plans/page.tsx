"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createPlan,
  fetchPlanFeatures,
  fetchPlans,
  updatePlan,
  type AdminPlan,
  type PlanCreateInput,
  type PlanFeatureSpec,
} from "@/lib/billing-api";

export default function PlansPage() {
  const [plans, setPlans] = useState<AdminPlan[]>([]);
  const [features, setFeatures] = useState<PlanFeatureSpec[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<AdminPlan | null>(null);
  const [creating, setCreating] = useState(false);

  // Form state
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [priceCents, setPriceCents] = useState(0);
  const [creditCents, setCreditCents] = useState(0);
  const [maxChannels, setMaxChannels] = useState<string>("");
  const [maxMessages, setMaxMessages] = useState<string>("");
  const [sortOrder, setSortOrder] = useState(0);
  const [isActive, setIsActive] = useState(true);
  const [featureFlags, setFeatureFlags] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, f] = await Promise.all([fetchPlans(), fetchPlanFeatures()]);
      setPlans(p ?? []);
      setFeatures(f ?? []);
      if (!creating && !editing) {
        const defaults: Record<string, boolean> = {};
        (f ?? []).forEach((spec) => { defaults[spec.key] = spec.default; });
        setFeatureFlags(defaults);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load plans.");
    } finally {
      setLoading(false);
    }
  }, [creating, editing]);

  useEffect(() => { load(); }, [load]);

  const resetForm = () => {
    setSlug(""); setName(""); setDescription("");
    setPriceCents(0); setCreditCents(0);
    setMaxChannels(""); setMaxMessages(""); setSortOrder(0); setIsActive(true);
    const defaults: Record<string, boolean> = {};
    features.forEach((spec) => { defaults[spec.key] = spec.default; });
    setFeatureFlags(defaults);
  };

  const startEdit = (p: AdminPlan) => {
    setCreating(false);
    setEditing(p);
    setSlug(p.slug); setName(p.name); setDescription(p.description ?? "");
    setPriceCents(p.price_cents); setCreditCents(p.included_credit_cents);
    setMaxChannels(p.max_channels == null ? "" : String(p.max_channels));
    setMaxMessages(p.max_messages_per_month == null ? "" : String(p.max_messages_per_month));
    setSortOrder(p.sort_order); setIsActive(p.is_active);
    const flags: Record<string, boolean> = {};
    features.forEach((spec) => { flags[spec.key] = !!(p.features || {})[spec.key]; });
    setFeatureFlags(flags);
  };

  const startCreate = () => {
    setEditing(null);
    setCreating(true);
    resetForm();
  };

  const cancelForm = () => {
    setCreating(false);
    setEditing(null);
    resetForm();
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const payload: PlanCreateInput = {
        slug: slug.trim(),
        name: name.trim(),
        description: description.trim() || null,
        price_cents: priceCents,
        included_credit_cents: creditCents,
        max_channels: maxChannels.trim() === "" ? null : Number(maxChannels),
        max_messages_per_month: maxMessages.trim() === "" ? null : Number(maxMessages),
        features: featureFlags,
        is_active: isActive,
        sort_order: sortOrder,
      };
      if (editing) {
        await updatePlan(editing.id, {
          name: payload.name,
          description: payload.description,
          price_cents: payload.price_cents,
          included_credit_cents: payload.included_credit_cents,
          max_channels: payload.max_channels,
          max_messages_per_month: payload.max_messages_per_month,
          features: payload.features,
          is_active: payload.is_active,
          sort_order: payload.sort_order,
        });
      } else {
        await createPlan(payload);
      }
      cancelForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setBusy(false);
    }
  };

  const toggleFeature = (key: string) => {
    setFeatureFlags((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-bold text-ink">Plans</h1>
          <p className="mt-0.5 text-[12px] text-ink/50">
            Define plans, pricing, limits, and which features each plan unlocks. Changes take effect for tenants on their next entitlement check.
          </p>
        </div>
        {!creating && !editing && (
          <button onClick={startCreate} className="btn-primary px-4 py-2 text-[12px] font-semibold">
            New plan
          </button>
        )}
      </div>

      {error && (
        <p role="alert" className="rounded-[2px] bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>
      )}

      {(creating || editing) && (
        <form onSubmit={submit} className="panel space-y-4 p-4">
          <p className="text-[12px] font-semibold text-ink">{editing ? `Edit ${editing.name}` : "New plan"}</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {!editing && (
              <div>
                <label className="mb-1 block text-[11px] font-medium text-ink/60">Slug</label>
                <input className="input-field" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="starter" required />
              </div>
            )}
            <div>
              <label className="mb-1 block text-[11px] font-medium text-ink/60">Name</label>
              <input className="input-field" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="sm:col-span-2">
              <label className="mb-1 block text-[11px] font-medium text-ink/60">Description</label>
              <input className="input-field" value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-ink/60">Price (cents/mo)</label>
              <input className="input-field" type="number" min={0} value={priceCents} onChange={(e) => setPriceCents(Number(e.target.value))} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-ink/60">Included AI credit (cents)</label>
              <input className="input-field" type="number" min={0} value={creditCents} onChange={(e) => setCreditCents(Number(e.target.value))} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-ink/60">Max channels (blank = unlimited)</label>
              <input className="input-field" type="number" min={1} value={maxChannels} onChange={(e) => setMaxChannels(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-ink/60">Max messages/month (blank = unlimited)</label>
              <input className="input-field" type="number" min={1} value={maxMessages} onChange={(e) => setMaxMessages(e.target.value)} />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-ink/60">Sort order</label>
              <input className="input-field" type="number" value={sortOrder} onChange={(e) => setSortOrder(Number(e.target.value))} />
            </div>
            <div className="flex items-center gap-2 pt-6">
              <input id="is_active" type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              <label htmlFor="is_active" className="text-[12px] text-ink">Active</label>
            </div>
          </div>

          <div>
            <p className="mb-2 text-[12px] font-semibold text-ink">Features</p>
            <p className="mb-3 text-[11px] text-ink/50">Check the features this plan unlocks. Unchecked features are denied to tenants on this plan.</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {features.map((spec) => (
                <label key={spec.key} className="flex items-start gap-2 rounded-[2px] border border-[var(--ui-line)] p-2 text-[12px]">
                  <input
                    type="checkbox"
                    checked={!!featureFlags[spec.key]}
                    onChange={() => toggleFeature(spec.key)}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-medium text-ink">{spec.label}</span>
                    <span className="block text-[10px] text-ink/50">{spec.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div className="flex gap-2">
            <button type="submit" disabled={busy || !name.trim()} className="btn-primary px-4 py-2 text-[12px] font-semibold disabled:opacity-50">
              {busy ? "Saving…" : editing ? "Save changes" : "Create plan"}
            </button>
            <button type="button" onClick={cancelForm} className="btn-ghost px-4 py-2 text-[12px] font-semibold">
              Cancel
            </button>
          </div>
        </form>
      )}

      <div className="panel overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="border-b border-[var(--ui-line)] text-left text-[11px] font-semibold uppercase tracking-wide text-ink/50">
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Slug</th>
              <th className="px-3 py-2">Price</th>
              <th className="px-3 py-2">Credit</th>
              <th className="px-3 py-2">Channels</th>
              <th className="px-3 py-2">Msgs/mo</th>
              <th className="px-3 py-2">Features</th>
              <th className="px-3 py-2">Active</th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9} className="px-3 py-6 text-center text-ink/40">Loading…</td></tr>
            ) : plans.length === 0 ? (
              <tr><td colSpan={9} className="px-3 py-6 text-center text-ink/40">No plans yet.</td></tr>
            ) : (
              plans.map((p) => (
                <tr key={p.id} className="border-b border-[var(--ui-line)] last:border-0">
                  <td className="px-3 py-2 font-medium text-ink">{p.name}</td>
                  <td className="px-3 py-2 text-ink/60">{p.slug}</td>
                  <td className="px-3 py-2">{(p.price_cents / 100).toFixed(2)}</td>
                  <td className="px-3 py-2">{(p.included_credit_cents / 100).toFixed(2)}</td>
                  <td className="px-3 py-2">{p.max_channels ?? "∞"}</td>
                  <td className="px-3 py-2">{p.max_messages_per_month ?? "∞"}</td>
                  <td className="px-3 py-2 text-[10px] text-ink/60">
                    {Object.entries(p.features || {}).filter(([, v]) => v).map(([k]) => k).join(", ") || "—"}
                  </td>
                  <td className="px-3 py-2">{p.is_active ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">
                    <button onClick={() => startEdit(p)} className="text-[11px] font-semibold text-deep-violet hover:underline">
                      Edit
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
