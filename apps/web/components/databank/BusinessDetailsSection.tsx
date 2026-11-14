"use client";

import { useEffect, useMemo, useState } from "react";
import {
  fetchBusinessDetails,
  saveBusinessDetails,
  type BusinessDetailsOut,
  type BusinessDetailsUser,
} from "@/lib/api-business-details";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const FOCUS_RING = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

type HoursShape = Record<string, { open: string; close: string; closed?: boolean }>;

function emptyWeek(): HoursShape {
  const out: HoursShape = {};
  for (const d of DAYS) out[d] = { open: "09:00", close: "17:00", closed: false };
  return out;
}

function hoursFromRaw(raw: Record<string, unknown> | undefined | null): HoursShape {
  const regular = (raw?.regular ?? {}) as Record<string, unknown>;
  const out: HoursShape = {};
  for (const d of DAYS) {
    const v = (regular[d] ?? {}) as { open?: string; close?: string; closed?: boolean };
    out[d] = {
      open: typeof v.open === "string" && v.open ? v.open : "09:00",
      close: typeof v.close === "string" && v.close ? v.close : "17:00",
      closed: v.closed === true,
    };
  }
  return out;
}

function categoriesFromRaw(raw: Record<string, unknown> | undefined | null): {
  category: string;
  subcategories: string;
  sub_subcategories: string;
} {
  const c = raw ?? {};
  return {
    category: String(c.category ?? ""),
    subcategories: Array.isArray(c.subcategories) ? (c.subcategories as string[]).join(", ") : "",
    sub_subcategories: Array.isArray(c.sub_subcategories) ? (c.sub_subcategories as string[]).join(", ") : "",
  };
}

function categoriesToRaw(v: { category: string; subcategories: string; sub_subcategories: string }): Record<string, unknown> {
  return {
    category: v.category.trim(),
    subcategories: v.subcategories.split(",").map((s) => s.trim()).filter(Boolean),
    sub_subcategories: v.sub_subcategories.split(",").map((s) => s.trim()).filter(Boolean),
  };
}

function servicesFromRaw(raw: unknown[] | undefined | null): string {
  if (!Array.isArray(raw)) return "";
  return raw.map((s) => (typeof s === "string" ? s : String((s as { label?: string })?.label ?? ""))).filter(Boolean).join(", ");
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function CompareLine({ label, googleValue, userValue }: { label: string; googleValue: string; userValue: string }) {
  if (googleValue === userValue) return null;
  return (
    <div className="rounded-[2px] border-l-2 border-amber-400 bg-amber-500/[0.06] px-3 py-2">
      <p className="text-[10px] font-bold uppercase tracking-wide text-amber-600">{label}</p>
      <p className="mt-0.5 text-[11px] text-ink/50">
        Google&apos;s record: <span className="font-semibold text-ink/70">{googleValue || "—"}</span>
      </p>
      <p className="text-[11px] text-ink/70">
        Yours: <span className="font-semibold text-deep-violet">{userValue || "—"}</span>
      </p>
    </div>
  );
}

export default function BusinessDetailsSection() {
  const [items, setItems] = useState<BusinessDetailsOut[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [cats, setCats] = useState({ category: "", subcategories: "", sub_subcategories: "" });
  const [services, setServices] = useState("");
  const [hours, setHours] = useState<HoursShape>(emptyWeek());
  const [special, setSpecial] = useState<{ date: string; open: string; close: string; closed: boolean }[]>([]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await fetchBusinessDetails();
      setItems(list);
      setSelected((prev) => (list.some((i) => i.listing_id === prev) ? prev : (list[0]?.listing_id ?? "")));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load business details.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, []);

  const current = useMemo(() => items.find((i) => i.listing_id === selected) ?? null, [items, selected]);

  // Prefill the form: merchant values when present, else Google's.
  useEffect(() => {
    if (!current) return;
    const u: BusinessDetailsUser | null = current.user;
    setName((u?.name ?? current.google.name) || "");
    setCats(categoriesFromRaw(u?.categories ?? current.google.categories));
    setServices(servicesFromRaw(u?.services ?? current.google.services));
    setHours(hoursFromRaw(u?.hours ?? current.google.hours));
    const sp = (u?.special_hours ?? current.google.special_hours) as { date?: string; open?: string; close?: string; closed?: boolean }[];
    setSpecial(
      (Array.isArray(sp) ? sp : []).map((s) => ({
        date: String(s.date ?? ""),
        open: String(s.open ?? "09:00"),
        close: String(s.close ?? "17:00"),
        closed: s.closed === true,
      })),
    );
    setSavedAt(u?.source === "edited" ? u.updated_at ?? null : null);
  }, [current]);

  const compare = useMemo(() => {
    if (!current || !current.user) return null;
    const u = current.user;
    const g = current.google;
    const catU = categoriesFromRaw(u.categories);
    const catG = categoriesFromRaw(g.categories);
    const gHours = hoursFromRaw(g.hours);
    const hSummary = (w: HoursShape) =>
      DAYS.map((d) => (w[d].closed ? "Closed" : `${w[d].open}–${w[d].close}`)).join(" | ");
    const spG = Array.isArray(g.special_hours) && g.special_hours.length ? JSON.stringify(g.special_hours) : "";
    const spU = JSON.stringify(special);
    return {
      name: { g: g.name, u: u.name ?? "" },
      category: { g: catG.category, u: catU.category },
      subcategories: { g: catG.subcategories, u: catU.subcategories },
      sub_subcategories: { g: catG.sub_subcategories, u: catU.sub_subcategories },
      services: { g: servicesFromRaw(g.services), u: servicesFromRaw(u.services) },
      hours: { g: hSummary(gHours), u: hSummary(hours) },
      special_hours: { g: spG, u: spU },
    };
  }, [current, hours, special]);

  const handleSave = async () => {
    if (!current) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await saveBusinessDetails(current.listing_id, {
        name: name.trim() || null,
        categories: categoriesToRaw(cats),
        services: services.split(",").map((s) => s.trim()).filter(Boolean),
        hours: { regular: hours },
        special_hours: special,
      });
      setItems((prev) => prev.map((i) => (i.listing_id === updated.listing_id ? updated : i)));
      setSavedAt(updated.user?.updated_at ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="ui-card h-40 animate-pulse" aria-hidden />;
  }

  return (
    <section className="ui-card p-5" aria-label="Business details">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-[14px] font-bold text-[var(--ui-ink)]">Business details</h3>
          <p className="mt-0.5 max-w-2xl text-[11.5px] leading-relaxed text-[var(--ui-ink-2)]">
            The AI answers with <strong>your details first</strong>. Google&apos;s data can lag for days or
            weeks (edits stuck “pending”), so tell us what&apos;s true today — the assistant stays fast and
            accurate. You can always see Google&apos;s official value next to yours.
          </p>
        </div>
        {savedAt && (
          <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-emerald-700">
            Saved {fmtTime(savedAt)}
          </span>
        )}
      </div>

      {items.length === 0 ? (
        <div className="mt-4 rounded-[2px] border border-dashed border-[var(--ui-line-strong)] p-6 text-center text-[12px] text-[var(--ui-ink-2)]">
          Connect a Google Business location in Channels first — its details will appear here automatically.
        </div>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-semibold text-[var(--ui-ink-2)]">Location:</span>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="input-field !w-auto font-medium"
              aria-label="Location"
            >
              {items.map((i) => (
                <option key={i.listing_id} value={i.listing_id}>{i.google.name || i.listing_id}</option>
              ))}
            </select>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {/* Form */}
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Business name</label>
                <input value={name} onChange={(e) => setName(e.target.value)} maxLength={255} className="input-field" />
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Category</label>
                  <input value={cats.category} onChange={(e) => setCats((c) => ({ ...c, category: e.target.value }))} placeholder="Restaurant" className="input-field" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Subcategories</label>
                  <input value={cats.subcategories} onChange={(e) => setCats((c) => ({ ...c, subcategories: e.target.value }))} placeholder="Café, Bakery" className="input-field" />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Sub-subcategories</label>
                  <input value={cats.sub_subcategories} onChange={(e) => setCats((c) => ({ ...c, sub_subcategories: e.target.value }))} placeholder="Desserts" className="input-field" />
                </div>
              </div>

              <div>
                <label className="mb-1 block text-[11px] font-semibold text-[var(--ui-ink-2)]">Services (comma separated)</label>
                <input value={services} onChange={(e) => setServices(e.target.value)} placeholder="Catering, Home delivery, Wi-Fi" className="input-field" />
              </div>

              {/* Hours */}
              <div>
                <p className="mb-1 text-[11px] font-semibold text-[var(--ui-ink-2)]">Regular hours</p>
                <div className="space-y-1.5">
                  {DAYS.map((d) => {
                    const row = hours[d];
                    return (
                      <div key={d} className="flex items-center gap-2 text-[11.5px]">
                        <span className="w-20 shrink-0 font-semibold text-[var(--ui-ink)]">{d}</span>
                        <label className="flex items-center gap-1.5 text-[11px] text-[var(--ui-ink-2)]">
                          <input type="checkbox" checked={row.closed} onChange={(e) => setHours((h) => ({ ...h, [d]: { ...h[d], closed: e.target.checked } }))} className="h-3.5 w-3.5 accent-deep-violet" />
                          Closed
                        </label>
                        <input type="time" value={row.open} disabled={row.closed} onChange={(e) => setHours((h) => ({ ...h, [d]: { ...h[d], open: e.target.value } }))} className="input-field !w-auto px-2 py-1 text-[11px] disabled:opacity-40" />
                        <span className="text-[var(--ui-ink-2)]">–</span>
                        <input type="time" value={row.close} disabled={row.closed} onChange={(e) => setHours((h) => ({ ...h, [d]: { ...h[d], close: e.target.value } }))} className="input-field !w-auto px-2 py-1 text-[11px] disabled:opacity-40" />
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Special hours */}
              <div>
                <p className="mb-1 text-[11px] font-semibold text-[var(--ui-ink-2)]">Special hours</p>
                {special.length === 0 && (
                  <p className="mb-1 text-[10.5px] text-[var(--ui-ink-2)]">None — add holidays or one-off changes below.</p>
                )}
                <div className="space-y-1.5">
                  {special.map((s, idx) => (
                    <div key={idx} className="flex flex-wrap items-center gap-2 text-[11.5px]">
                      <input type="date" value={s.date} onChange={(e) => setSpecial((arr) => arr.map((x, i) => (i === idx ? { ...x, date: e.target.value } : x)))} className="input-field !w-auto px-2 py-1 text-[11px]" />
                      <label className="flex items-center gap-1.5 text-[11px] text-[var(--ui-ink-2)]">
                        <input type="checkbox" checked={s.closed} onChange={(e) => setSpecial((arr) => arr.map((x, i) => (i === idx ? { ...x, closed: e.target.checked } : x)))} className="h-3.5 w-3.5 accent-deep-violet" />
                        Closed
                      </label>
                      {!s.closed && (
                        <>
                          <input type="time" value={s.open} onChange={(e) => setSpecial((arr) => arr.map((x, i) => (i === idx ? { ...x, open: e.target.value } : x)))} className="input-field !w-auto px-2 py-1 text-[11px]" />
                          <span className="text-[var(--ui-ink-2)]">–</span>
                          <input type="time" value={s.close} onChange={(e) => setSpecial((arr) => arr.map((x, i) => (i === idx ? { ...x, close: e.target.value } : x)))} className="input-field !w-auto px-2 py-1 text-[11px]" />
                        </>
                      )}
                      <button type="button" onClick={() => setSpecial((arr) => arr.filter((_, i) => i !== idx))} className="rounded-[2px] px-1.5 py-1 text-[11px] font-semibold text-[var(--ui-ink-2)] transition hover:text-coral" aria-label={`Remove special hour ${idx + 1}`}>✕</button>
                    </div>
                  ))}
                </div>
                <button type="button" onClick={() => setSpecial((arr) => [...arr, { date: "", open: "09:00", close: "17:00", closed: false }])} className="mt-2 rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-[var(--ui-ink)] transition hover:border-deep-violet hover:text-deep-violet">
                  + Add special hours
                </button>
              </div>

              {error && <p role="alert" className="rounded-[2px] border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700">{error}</p>}

              <button type="button" onClick={() => void handleSave()} disabled={saving} className={`btn-primary !px-4 !py-2 disabled:opacity-50 ${FOCUS_RING}`}>
                {saving ? "Saving…" : "Save details"}
              </button>
            </div>

            {/* Compare: Google official vs merchant */}
            <div className="space-y-2">
              <p className="text-[11px] font-bold uppercase tracking-wide text-[var(--ui-ink-2)]">Google&apos;s record vs yours</p>
              {compare ? (
                <>
                  <CompareLine label="Name" googleValue={compare.name.g} userValue={compare.name.u} />
                  <CompareLine label="Category" googleValue={compare.category.g} userValue={compare.category.u} />
                  <CompareLine label="Subcategories" googleValue={compare.subcategories.g} userValue={compare.subcategories.u} />
                  <CompareLine label="Sub-subcategories" googleValue={compare.sub_subcategories.g} userValue={compare.sub_subcategories.u} />
                  <CompareLine label="Services" googleValue={compare.services.g} userValue={compare.services.u} />
                  <CompareLine label="Regular hours" googleValue={compare.hours.g} userValue={compare.hours.u} />
                  <CompareLine label="Special hours" googleValue={compare.special_hours.g} userValue={compare.special_hours.u} />
                  {!Object.values(compare).some((c) => c.g !== c.u) && (
                    <p className="rounded-[2px] border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11.5px] font-medium text-emerald-700">
                      Your details match Google — nothing differs.
                    </p>
                  )}
                </>
              ) : (
                <p className="rounded-[2px] border border-dashed border-[var(--ui-line-strong)] px-3 py-3 text-[11.5px] text-[var(--ui-ink-2)]">
                  You haven&apos;t edited anything here yet. Save once to see Google&apos;s official value next to yours for every change.
                </p>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
