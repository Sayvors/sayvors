"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

/* ΓöÇΓöÇ Types ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */

interface Location {
  id: string;
  name: string;
  address: string;
  phone: string;
  website: string;
  status: string;
  categories: string[];
  primary_category: string;
  description: string;
  regular_hours: Record<string, string>;
  special_hours: Record<string, string>;
  service_area: string[];
  attributes: Record<string, string>;
  permanently_closed: boolean;
}

interface LocationOption {
  id: string;
  name: string;
  address: string;
  status: string;
}

const HOURS_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/* ΓöÇΓöÇ Page ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */

export default function LocationsPage() {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>("details");
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const googleChannels = (data.channels ?? [])
          .filter((channel: { platform: string }) => channel.platform === "google_reviews")
          .map((channel: { id: string; display_name: string | null; status: string }) => ({
            id: channel.id,
            name: channel.display_name ?? "",
            address: "",
            status: channel.status,
          }));
        if (!cancelled) {
          setLocations(googleChannels);
          if (googleChannels.length) setSelectedId(googleChannels[0].id);
        }
      } catch {
        setLocations([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const selectedLocation = locations.find((l) => l.id === selectedId) ?? locations[0] ?? null;


  const tabs = [
    { key: "details", label: "Business Details" },
    { key: "categories", label: "Categories" },
    { key: "hours", label: "Hours" },
    { key: "special-hours", label: "Special Hours" },
    { key: "more-hours", label: "More Hours" },
    { key: "service-area", label: "Service Area" },
    { key: "attributes", label: "Attributes" },
    { key: "description", label: "Description" },
    { key: "google-updates", label: "Google Updates" },
  ];

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Locations</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
            Manage your business locations on Google.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Location selector dropdown */}
          <div className="relative">
            <select
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value)}
              className="w-56 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              {locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name}
                </option>
              ))}
              {locations.length === 0 && <option value="">No locations</option>}
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40 dark:text-fog/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </div>
          <span className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${locations.length ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
            {locations.length ? "Google connected" : "Google not connected"}
          </span>
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

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <LogoLoader size={32} />
        </div>
      ) : (
        <>
          {/* Tabs */}
          <div className="flex gap-1 overflow-x-auto rounded-xl bg-ink/[0.03] p-1 dark:bg-fog/[0.04]">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                  activeTab === tab.key
                    ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-fog"
                    : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
            {activeTab === "details" && (
              <DetailsTab location={selectedLocation} onSave={() => setBanner({ kind: "ok", text: "Details saved." })} />
            )}
            {activeTab === "categories" && (
              <CategoriesTab location={selectedLocation} onSave={() => setBanner({ kind: "ok", text: "Categories updated." })} />
            )}
            {activeTab === "hours" && (
              <HoursTab location={selectedLocation} onSave={() => setBanner({ kind: "ok", text: "Hours saved." })} />
            )}
            {activeTab === "special-hours" && (
              <SpecialHoursTab location={selectedLocation} onSave={() => setBanner({ kind: "ok", text: "Special hours saved." })} />
            )}
            {activeTab === "more-hours" && (
              <MoreHoursTab location={selectedLocation} onSave={() => setBanner({ kind: "ok", text: "More hours saved." })} />
            )}
            {activeTab === "service-area" && (
              <ServiceAreaTab location={selectedLocation} onSave={() => setBanner({ kind: "ok", text: "Service area saved." })} />
            )}
            {activeTab === "attributes" && (
              <AttributesTab location={selectedLocation} onSave={() => setBanner({ kind: "ok", text: "Attributes saved." })} />
            )}
            {activeTab === "description" && (
              <DescriptionTab location={selectedLocation} onSave={() => setBanner({ kind: "ok", text: "Description saved." })} />
            )}
            {activeTab === "google-updates" && (
              <GoogleUpdatesTab />
            )}
          </div>

        </>
      )}
    </div>
  );
}

/* ΓöÇΓöÇ Tab Panels ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */

function DetailsTab({ location, onSave }: { location: LocationOption | null; onSave: () => void }) {
  const [name, setName] = useState(location?.name ?? "");
  const [address, setAddress] = useState(location?.address ?? "");
  const [phone, setPhone] = useState("");
  const [website, setWebsite] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setName(location?.name ?? "");
    setAddress(location?.address ?? "");
  }, [location?.id]);

  const handleSave = async () => {
    setSaving(true);
    try {
      onSave();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <SectionTitle title="Business Details" subtitle="Edit your location's core information." />
      <Field label="Business Name">
        <input value={name} onChange={(e) => setName(e.target.value)} className="input-field" />
      </Field>
      <Field label="Address">
        <input value={address} onChange={(e) => setAddress(e.target.value)} className="input-field" />
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Phone">
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+966 55 000 0000" className="input-field" />
        </Field>
        <Field label="Website">
          <input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://..." className="input-field" />
        </Field>
      </div>
      <Field label="Status">
        <div className="flex items-center gap-2">
          <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full ${location?.status === "active" ? "bg-emerald-100 text-emerald-600" : "bg-ink/10 text-ink/40"}`}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3 w-3"><path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </span>
          <span className="text-[13px] capitalize text-ink dark:text-fog">{location?.status ?? ""}</span>
        </div>
      </Field>
      <div className="flex justify-end pt-2">
        <button onClick={handleSave} disabled={saving} className="btn-primary">
          {saving ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : "Save Changes"}
        </button>
      </div>
    </div>
  );
}

function CategoriesTab({ location, onSave }: { location: LocationOption | null; onSave: () => void }) {
  const [primary, setPrimary] = useState("");
  const [additional, setAdditional] = useState<string[]>([]);
  const [newCat, setNewCat] = useState("");
  const [saving, setSaving] = useState(false);

  const addCategory = () => {
    if (newCat.trim() && !additional.includes(newCat.trim())) {
      setAdditional([...additional, newCat.trim()]);
      setNewCat("");
    }
  };

  const removeCategory = (cat: string) => setAdditional(additional.filter((c) => c !== cat));

  return (
    <div className="space-y-5">
      <SectionTitle title="Categories" subtitle="Your business categories on Google." />
      <Field label="Primary Category">
        <input value={primary} onChange={(e) => setPrimary(e.target.value)} className="input-field" />
      </Field>
      <Field label="Additional Categories">
        <div className="flex flex-wrap gap-2 mb-2">
          {additional.map((cat) => (
            <span key={cat} className="inline-flex items-center gap-1 rounded-full bg-deep-violet/10 px-2.5 py-1 text-[12px] font-medium text-deep-violet">
              {cat}
              <button onClick={() => removeCategory(cat)} className="ml-0.5 text-deep-violet/50 hover:text-deep-violet">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input value={newCat} onChange={(e) => setNewCat(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addCategory()} placeholder="Add category..." className="input-field flex-1" />
          <button onClick={addCategory} className="btn-secondary">Add</button>
        </div>
      </Field>
      <div className="flex justify-end pt-2">
        <button onClick={onSave} className="btn-primary">Save Categories</button>
      </div>
    </div>
  );
}

function HoursTab({ location, onSave }: { location: LocationOption | null; onSave: () => void }) {
  const [hours, setHours] = useState<Record<string, { open: string; close: string; closed: boolean }>>(
    Object.fromEntries(HOURS_DAYS.map((d) => [d, { open: "", close: "", closed: false }]))
  );

  const updateDay = (day: string, field: string, value: string | boolean) => {
    setHours({ ...hours, [day]: { ...hours[day], [field]: value } });
  };

  return (
    <div className="space-y-5">
      <SectionTitle title="Regular Hours" subtitle="Set your standard opening hours for each day." />
      <div className="space-y-2">
        {HOURS_DAYS.map((day) => (
          <div key={day} className="flex items-center gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
            <span className="w-24 text-[13px] font-medium text-ink dark:text-fog">{day}</span>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={!hours[day].closed}
                onChange={(e) => updateDay(day, "closed", !e.target.checked)}
                className="h-4 w-4 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/40"
              />
              <span className="text-[12px] text-ink/50 dark:text-fog/50">Open</span>
            </label>
            {!hours[day].closed ? (
              <div className="flex items-center gap-2">
                <input type="time" value={hours[day].open} onChange={(e) => updateDay(day, "open", e.target.value)} className="input-field w-28" />
                <span className="text-[12px] text-ink/40">to</span>
                <input type="time" value={hours[day].close} onChange={(e) => updateDay(day, "close", e.target.value)} className="input-field w-28" />
              </div>
            ) : (
              <span className="text-[12px] font-medium text-ink/30 dark:text-fog/30">Closed</span>
            )}
          </div>
        ))}
      </div>
      <div className="flex justify-end pt-2">
        <button onClick={onSave} className="btn-primary">Save Hours</button>
      </div>
    </div>
  );
}

function SpecialHoursTab({ location, onSave }: { location: LocationOption | null; onSave: () => void }) {
  const [entries, setEntries] = useState<{ date: string; hours: string; reason: string }[]>([]);
  const addEntry = () => setEntries([...entries, { date: "", hours: "09:00 - 17:00", reason: "" }]);
  const removeEntry = (i: number) => setEntries(entries.filter((_, idx) => idx !== i));
  const updateEntry = (i: number, field: string, value: string) => {
    const next = [...entries];
    (next[i] as any)[field] = value;
    setEntries(next);
  };

  return (
    <div className="space-y-5">
      <SectionTitle title="Special / Holiday Hours" subtitle="Override regular hours for specific dates (holidays, events)." />
      {entries.map((entry, i) => (
        <div key={i} className="flex items-start gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
          <input type="date" value={entry.date} onChange={(e) => updateEntry(i, "date", e.target.value)} className="input-field w-40" />
          <input value={entry.hours} onChange={(e) => updateEntry(i, "hours", e.target.value)} placeholder="09:00 - 17:00" className="input-field w-40" />
          <input value={entry.reason} onChange={(e) => updateEntry(i, "reason", e.target.value)} placeholder="Reason (e.g. Holiday)" className="input-field flex-1" />
          <button onClick={() => removeEntry(i)} className="mt-1 text-ink/30 transition hover:text-red-500 dark:text-fog/30">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
          </button>
        </div>
      ))}
      <button onClick={addEntry} className="btn-secondary">+ Add Special Hours</button>
      <div className="flex justify-end pt-2">
        <button onClick={onSave} className="btn-primary">Save Special Hours</button>
      </div>
    </div>
  );
}

const MORE_HOURS_OPTIONS = ["Access", "Brunch", "Delivery", "Dinner", "Happy Hour", "Lunch", "Takeout", "Drive-through"];

function MoreHoursTab({ location, onSave }: { location: LocationOption | null; onSave: () => void }) {
  const [entries, setEntries] = useState<{ type: string; open: string; close: string }[]>([]);
  const addEntry = () => setEntries([...entries, { type: MORE_HOURS_OPTIONS[0], open: "09:00", close: "17:00" }]);
  const removeEntry = (i: number) => setEntries(entries.filter((_, idx) => idx !== i));
  const updateEntry = (i: number, field: string, value: string) => {
    const next = [...entries];
    (next[i] as any)[field] = value;
    setEntries(next);
  };

  return (
    <div className="space-y-5">
      <SectionTitle title="More Hours" subtitle="Additional service hours (delivery, drive-through, takeout, etc.)." />
      {entries.length === 0 && (
        <p className="text-[12px] text-ink/35 dark:text-fog/35">No additional hours set. Add entries for services like delivery or drive-through.</p>
      )}
      {entries.map((entry, i) => (
        <div key={i} className="flex items-center gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
          <select value={entry.type} onChange={(e) => updateEntry(i, "type", e.target.value)} className="input-field w-40">
            {MORE_HOURS_OPTIONS.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
          </select>
          <input type="time" value={entry.open} onChange={(e) => updateEntry(i, "open", e.target.value)} className="input-field w-28" />
          <span className="text-[12px] text-ink/40">to</span>
          <input type="time" value={entry.close} onChange={(e) => updateEntry(i, "close", e.target.value)} className="input-field w-28" />
          <button onClick={() => removeEntry(i)} className="text-ink/30 transition hover:text-red-500 dark:text-fog/30">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
          </button>
        </div>
      ))}
      <button onClick={addEntry} className="btn-secondary">+ Add More Hours</button>
      <div className="flex justify-end pt-2">
        <button onClick={onSave} className="btn-primary">Save More Hours</button>
      </div>
    </div>
  );
}

function ServiceAreaTab({ location, onSave }: { location: LocationOption | null; onSave: () => void }) {
  const [areas, setAreas] = useState<string[]>([]);
  const [newArea, setNewArea] = useState("");

  const addArea = () => {
    if (newArea.trim() && !areas.includes(newArea.trim())) {
      setAreas([...areas, newArea.trim()]);
      setNewArea("");
    }
  };

  return (
    <div className="space-y-5">
      <SectionTitle title="Service Area" subtitle="Define the geographic areas your business serves." />
      <div className="flex flex-wrap gap-2 mb-3">
        {areas.map((area) => (
          <span key={area} className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2.5 py-1 text-[12px] font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">
            {area}
            <button onClick={() => setAreas(areas.filter((a) => a !== area))} className="ml-0.5 text-sky-500/50 hover:text-sky-700">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <input value={newArea} onChange={(e) => setNewArea(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addArea()} placeholder="Add area..." className="input-field flex-1" />
        <button onClick={addArea} className="btn-secondary">Add</button>
      </div>
      <div className="flex justify-end pt-2">
        <button onClick={onSave} className="btn-primary">Save Service Area</button>
      </div>
    </div>
  );
}

function AttributesTab({ location, onSave }: { location: LocationOption | null; onSave: () => void }) {
  const [attrs, setAttrs] = useState<Record<string, string>>({});

  return (
    <div className="space-y-5">
      <SectionTitle title="Attributes" subtitle="Category-specific attributes (accessibility, amenities, payment, etc.)." />
      <div className="space-y-3">
        {Object.entries(attrs).length === 0 && <p className="text-[12px] text-ink/35 dark:text-fog/35">No attributes stored yet.</p>}
        {Object.entries(attrs).map(([key, value]) => (
          <div key={key} className="grid grid-cols-[160px_1fr] items-center gap-3">
            <span className="text-[13px] font-medium text-ink dark:text-fog">{key}</span>
            <input
              value={value}
              onChange={(e) => setAttrs({ ...attrs, [key]: e.target.value })}
              className="input-field"
            />
          </div>
        ))}
      </div>
      <div className="flex justify-end pt-2">
        <button onClick={onSave} className="btn-primary">Save Attributes</button>
      </div>
    </div>
  );
}

function DescriptionTab({ location, onSave }: { location: LocationOption | null; onSave: () => void }) {
  const [desc, setDesc] = useState("");

  return (
    <div className="space-y-5">
      <SectionTitle title="Business Description" subtitle="Tell customers what your business is about." />
      <textarea
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        rows={6}
        maxLength={750}
        className="w-full resize-y rounded-xl border border-ink/[0.08] bg-white p-3 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
      />
      <p className="text-right text-[11px] text-ink/30 dark:text-fog/30">{desc.length}/750</p>
      <div className="flex justify-end pt-2">
        <button onClick={onSave} className="btn-primary">Save Description</button>
      </div>
    </div>
  );
}

function GoogleUpdatesTab() {
  const [updates, setUpdates] = useState<{ id: string; field: string; current: string; proposed: string; status: string }[]>([]);

  return (
    <div className="space-y-5">
      <SectionTitle title="Google Updates" subtitle="Review changes proposed by Google based on external sources." />
      {updates.length === 0 ? (
        <div className="flex flex-col items-center py-10">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="mb-2 h-8 w-8 text-ink/20 dark:text-fog/20">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14" strokeLinecap="round" />
            <path d="M22 4L12 14.01l-3-3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <p className="text-[13px] text-ink/40 dark:text-fog/40">No pending updates from Google.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {updates.map((u) => (
            <div key={u.id} className="flex items-center gap-4 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
              <div className="flex-1">
                <p className="text-[12px] font-semibold text-ink dark:text-fog">{u.field}</p>
                <p className="text-[11px] text-ink/40 dark:text-fog/40">Current: {u.current}</p>
                <p className="text-[11px] text-deep-violet">Proposed: {u.proposed}</p>
              </div>
              <button className="rounded-lg bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-600">Accept</button>
              <button className="rounded-lg border border-ink/[0.1] px-2.5 py-1 text-[11px] font-semibold text-ink/50 hover:bg-ink/[0.04] dark:text-fog/50">Reject</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ΓöÇΓöÇ Add Location Modal ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */

/* ΓöÇΓöÇ Shared pieces ΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇΓöÇ */

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-1">
      <h3 className="text-[14px] font-semibold text-ink dark:text-fog">{title}</h3>
      <p className="text-[12px] text-ink/40 dark:text-fog/40">{subtitle}</p>
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

function EmptyState() {
  return (
    <div className="flex flex-col items-center py-10">
      <p className="text-[13px] text-ink/40 dark:text-fog/40">Select a location to manage.</p>
    </div>
  );
}

function LocationIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

