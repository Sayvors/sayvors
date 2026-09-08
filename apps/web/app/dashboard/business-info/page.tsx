"use client";

import { Suspense, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

const HOURS_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const MORE_HOURS_OPTIONS = [
  "Access",
  "Brunch",
  "Delivery",
  "Dinner",
  "Happy Hour",
  "Lunch",
  "Takeout",
  "Drive-through",
];

export default function BusinessInfoPage() {
  return (
    <Suspense>
      <BusinessInfoInner />
    </Suspense>
  );
}

function BusinessInfoInner() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // ── Core fields ──
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [website, setWebsite] = useState("");

  // ── Categories ──
  const [primaryCategory, setPrimaryCategory] = useState("");
  const [additionalCategories, setAdditionalCategories] = useState<string[]>([]);
  const [newCategory, setNewCategory] = useState("");

  // ── Regular hours ──
  const [regularHours, setRegularHours] = useState<Record<string, { open: string; close: string; closed: boolean }>>(
    Object.fromEntries(HOURS_DAYS.map((d) => [d, { open: "09:00", close: "17:00", closed: d === "Friday" }]))
  );

  // ── Special hours ──
  const [specialHours, setSpecialHours] = useState<{ date: string; hours: string; reason: string }[]>([]);

  // ── More hours ──
  const [moreHours, setMoreHours] = useState<{ type: string; open: string; close: string }[]>([]);

  // ── Service area ──
  const [serviceAreas, setServiceAreas] = useState<string[]>([]);
  const [newArea, setNewArea] = useState("");

  // ── Attributes ──
  const [attributes, setAttributes] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/business-info");
        if (cancelled) return;
        setName(data.name ?? "");
        setDescription(data.description ?? "");
        setAddress(data.address ?? "");
        setPhone(data.phone ?? "");
        setWebsite(data.website ?? "");
        setPrimaryCategory(data.primary_category ?? "");
        setAdditionalCategories(data.additional_categories ?? []);
        setRegularHours(data.regular_hours ?? Object.fromEntries(HOURS_DAYS.map((d) => [d, { open: "09:00", close: "17:00", closed: d === "Friday" }])));
        setSpecialHours(data.special_hours ?? []);
        setMoreHours(data.more_hours ?? []);
        setServiceAreas(data.service_areas ?? []);
        setAttributes(data.attributes ?? {});
      } catch {
        /* not connected yet — show empty form */
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiFetch("/api/v1/business-info", {
        method: "PUT",
        body: JSON.stringify({
          name, description, address, phone, website,
          primary_category: primaryCategory,
          additional_categories: additionalCategories,
          regular_hours: regularHours,
          special_hours: specialHours,
          more_hours: moreHours,
          service_areas: serviceAreas,
          attributes,
        }),
      });
      setBanner({ kind: "ok", text: "Business information saved." });
    } catch {
      setBanner({ kind: "err", text: "Could not save. Please try again." });
    }
    setSaving(false);
  };

  const addCategory = () => {
    if (newCategory.trim() && !additionalCategories.includes(newCategory.trim())) {
      setAdditionalCategories([...additionalCategories, newCategory.trim()]);
      setNewCategory("");
    }
  };

  const addSpecialHours = () => setSpecialHours([...specialHours, { date: "", hours: "09:00 - 17:00", reason: "" }]);
  const removeSpecialHours = (i: number) => setSpecialHours(specialHours.filter((_, idx) => idx !== i));
  const updateSpecialHours = (i: number, field: string, value: string) => {
    const next = [...specialHours];
    (next[i] as any)[field] = value;
    setSpecialHours(next);
  };

  const addMoreHours = () => setMoreHours([...moreHours, { type: MORE_HOURS_OPTIONS[0], open: "09:00", close: "17:00" }]);
  const removeMoreHours = (i: number) => setMoreHours(moreHours.filter((_, idx) => idx !== i));
  const updateMoreHours = (i: number, field: string, value: string) => {
    const next = [...moreHours];
    (next[i] as any)[field] = value;
    setMoreHours(next);
  };

  const addArea = () => {
    if (newArea.trim() && !serviceAreas.includes(newArea.trim())) {
      setServiceAreas([...serviceAreas, newArea.trim()]);
      setNewArea("");
    }
  };

  const addAttribute = () => {
    const key = `Attribute ${Object.keys(attributes).length + 1}`;
    setAttributes({ ...attributes, [key]: "" });
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LogoLoader size={32} />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6 space-y-6 max-w-3xl">
      {/* Header */}
      <div>
        <h1 className="text-[20px] font-bold text-ink dark:text-fog">Business Information</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
          Manage your public business profile on Google.
        </p>
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

      {/* ── Core Info ── */}
      <Section title="Basic Information" subtitle="Your business name, description, and contact details.">
        <Field label="Business Name">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sayvors" className="input-field" />
        </Field>
        <Field label="Description">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            maxLength={750}
            placeholder="Tell customers what your business is about..."
            className="input-field resize-y"
          />
          <p className="mt-1 text-right text-[11px] text-ink/30 dark:text-fog/30">{description.length}/750</p>
        </Field>
        <Field label="Address">
          <input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Full street address" className="input-field" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Phone">
            <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+966 55 000 0000" className="input-field" />
          </Field>
          <Field label="Website">
            <input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://..." className="input-field" />
          </Field>
        </div>
      </Section>

      {/* ── Categories ── */}
      <Section title="Categories" subtitle="Help customers find you by choosing the right categories.">
        <Field label="Primary Category">
          <input value={primaryCategory} onChange={(e) => setPrimaryCategory(e.target.value)} placeholder="e.g. Restaurant, Plumber" className="input-field" />
        </Field>
        <Field label="Additional Categories">
          <div className="flex flex-wrap gap-2 mb-2">
            {additionalCategories.map((cat) => (
              <Tag key={cat} label={cat} onRemove={() => setAdditionalCategories(additionalCategories.filter((c) => c !== cat))} />
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addCategory()}
              placeholder="Add category..."
              className="input-field flex-1"
            />
            <button onClick={addCategory} className="btn-secondary">Add</button>
          </div>
        </Field>
      </Section>

      {/* ── Regular Hours ── */}
      <Section title="Regular Hours" subtitle="Your standard opening hours for each day.">
        <div className="space-y-2">
          {HOURS_DAYS.map((day) => (
            <div key={day} className="flex items-center gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
              <span className="w-24 text-[13px] font-medium text-ink dark:text-fog">{day}</span>
              <label className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={!regularHours[day]?.closed}
                  onChange={(e) => setRegularHours({ ...regularHours, [day]: { ...regularHours[day], closed: !e.target.checked } })}
                  className="h-4 w-4 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/40"
                />
                <span className="text-[12px] text-ink/50 dark:text-fog/50">Open</span>
              </label>
              {!regularHours[day]?.closed ? (
                <div className="flex items-center gap-2">
                  <input type="time" value={regularHours[day]?.open} onChange={(e) => setRegularHours({ ...regularHours, [day]: { ...regularHours[day], open: e.target.value } })} className="input-field w-28" />
                  <span className="text-[12px] text-ink/40">to</span>
                  <input type="time" value={regularHours[day]?.close} onChange={(e) => setRegularHours({ ...regularHours, [day]: { ...regularHours[day], close: e.target.value } })} className="input-field w-28" />
                </div>
              ) : (
                <span className="text-[12px] font-medium text-ink/30 dark:text-fog/30">Closed</span>
              )}
            </div>
          ))}
        </div>
      </Section>

      {/* ── Special Hours ── */}
      <Section title="Special / Holiday Hours" subtitle="Override regular hours for specific dates.">
        <div className="space-y-2">
          {specialHours.map((entry, i) => (
            <div key={i} className="flex items-start gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
              <input type="date" value={entry.date} onChange={(e) => updateSpecialHours(i, "date", e.target.value)} className="input-field w-40" />
              <input value={entry.hours} onChange={(e) => updateSpecialHours(i, "hours", e.target.value)} placeholder="09:00 - 17:00" className="input-field w-40" />
              <input value={entry.reason} onChange={(e) => updateSpecialHours(i, "reason", e.target.value)} placeholder="Reason (e.g. Holiday)" className="input-field flex-1" />
              <button onClick={() => removeSpecialHours(i)} className="mt-1 text-ink/30 transition hover:text-red-500 dark:text-fog/30">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
              </button>
            </div>
          ))}
        </div>
        <button onClick={addSpecialHours} className="btn-secondary mt-2">+ Add Special Hours</button>
      </Section>

      {/* ── More Hours ── */}
      <Section title="More Hours" subtitle="Additional service hours (delivery, drive-through, etc.).">
        <div className="space-y-2">
          {moreHours.map((entry, i) => (
            <div key={i} className="flex items-center gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
              <select
                value={entry.type}
                onChange={(e) => updateMoreHours(i, "type", e.target.value)}
                className="input-field w-40"
              >
                {MORE_HOURS_OPTIONS.map((opt) => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
              <input type="time" value={entry.open} onChange={(e) => updateMoreHours(i, "open", e.target.value)} className="input-field w-28" />
              <span className="text-[12px] text-ink/40">to</span>
              <input type="time" value={entry.close} onChange={(e) => updateMoreHours(i, "close", e.target.value)} className="input-field w-28" />
              <button onClick={() => removeMoreHours(i)} className="text-ink/30 transition hover:text-red-500 dark:text-fog/30">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
              </button>
            </div>
          ))}
        </div>
        <button onClick={addMoreHours} className="btn-secondary mt-2">+ Add More Hours</button>
      </Section>

      {/* ── Service Area ── */}
      <Section title="Service Area" subtitle="The geographic areas your business serves.">
        <div className="flex flex-wrap gap-2 mb-3">
          {serviceAreas.map((area) => (
            <Tag key={area} label={area} color="sky" onRemove={() => setServiceAreas(serviceAreas.filter((a) => a !== area))} />
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={newArea}
            onChange={(e) => setNewArea(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && addArea()}
            placeholder="Add area..."
            className="input-field flex-1"
          />
          <button onClick={addArea} className="btn-secondary">Add</button>
        </div>
      </Section>

      {/* ── Attributes ── */}
      <Section title="Attributes" subtitle="Category-specific attributes (accessibility, amenities, payments, etc.).">
        <div className="space-y-3">
          {Object.entries(attributes).map(([key, value]) => (
            <div key={key} className="grid grid-cols-[180px_1fr] items-center gap-3">
              <input
                value={key}
                onChange={(e) => {
                  const val = attributes[key];
                  const next = { ...attributes };
                  delete next[key];
                  next[e.target.value] = val;
                  setAttributes(next);
                }}
                className="input-field text-[12px] font-medium"
              />
              <div className="flex gap-2">
                <input
                  value={value}
                  onChange={(e) => setAttributes({ ...attributes, [key]: e.target.value })}
                  className="input-field flex-1"
                />
                <button
                  onClick={() => {
                    const next = { ...attributes };
                    delete next[key];
                    setAttributes(next);
                  }}
                  className="text-ink/30 transition hover:text-red-500 dark:text-fog/30"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
                </button>
              </div>
            </div>
          ))}
        </div>
        <button onClick={addAttribute} className="btn-secondary mt-2">+ Add Attribute</button>
      </Section>

      {/* ── Save ── */}
      <div className="flex justify-end border-t border-ink/[0.06] pt-4 dark:border-fog/[0.06]">
        <button onClick={handleSave} disabled={saving} className="btn-primary">
          {saving ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : "Save All Changes"}
        </button>
      </div>
    </div>
  );
}

/* ── Shared Components ─────────────────────────── */

function Section({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
      <div className="mb-4">
        <h2 className="text-[14px] font-semibold text-ink dark:text-fog">{title}</h2>
        <p className="text-[12px] text-ink/40 dark:text-fog/40">{subtitle}</p>
      </div>
      <div className="space-y-4">
        {children}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-ink/60 dark:text-fog/60">{label}</label>
      {children}
    </div>
  );
}

function Tag({ label, color = "violet", onRemove }: { label: string; color?: string; onRemove: () => void }) {
  const colors: Record<string, string> = {
    violet: "bg-deep-violet/10 text-deep-violet",
    sky: "bg-sky-100 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[12px] font-medium ${colors[color] ?? colors.violet}`}>
      {label}
      <button onClick={onRemove} className="ml-0.5 opacity-50 hover:opacity-100">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
      </button>
    </span>
  );
}
