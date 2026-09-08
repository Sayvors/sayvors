"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

interface LocationOption {
  id: string;
  name: string;
  address: string;
  primary_category: string;
}

interface ServiceItem {
  id: string;
  name: string;
  category: string;
  is_offered: boolean;
  is_custom: boolean;
}

const MOCK_LOCATIONS: LocationOption[] = [
  { id: "loc_1", name: "Sayvors Al Malqa", address: "Al Malqa, Riyadh", primary_category: "Software Company" },
];

export default function ServicesPage() {
  return (
    <Suspense>
      <ServicesInner />
    </Suspense>
  );
}

function ServicesInner() {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [services, setServices] = useState<ServiceItem[]>([]);
  const [predefined, setPredefined] = useState<ServiceItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [addTab, setAddTab] = useState<"google" | "custom">("google");
  const [search, setSearch] = useState("");
  const [customName, setCustomName] = useState("");
  const [customCategory, setCustomCategory] = useState("");
  const [hasChanges, setHasChanges] = useState(false);

  const selectedLocation = locations.find((l) => l.id === selectedId);

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
        const data = await apiFetch(`/api/v1/locations/${selectedId}/services`);
        if (!cancelled) {
          setServices(data.services ?? []);
          setPredefined(data.predefined ?? []);
        }
      } catch {
        if (!cancelled) {
          setServices([]);
          setPredefined([]);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  const toggleOffered = (id: string) => {
    setServices((prev) => prev.map((s) => s.id === id ? { ...s, is_offered: !s.is_offered } : s));
    setHasChanges(true);
  };

  const addPredefined = (svc: ServiceItem) => {
    if (!services.find((s) => s.id === svc.id)) {
      setServices((prev) => [...prev, { ...svc, is_offered: true }]);
      setHasChanges(true);
    }
  };

  const addCustom = () => {
    if (!customName.trim()) return;
    const newSvc: ServiceItem = {
      id: `custom_${Date.now()}`,
      name: customName.trim(),
      category: customCategory.trim() || "Custom",
      is_offered: true,
      is_custom: true,
    };
    setServices((prev) => [...prev, newSvc]);
    setCustomName("");
    setCustomCategory("");
    setShowAdd(false);
    setHasChanges(true);
  };

  const removeService = (id: string) => {
    setServices((prev) => prev.filter((s) => s.id !== id));
    setHasChanges(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/services`, {
        method: "PUT",
        body: JSON.stringify({ services }),
      });
      setHasChanges(false);
      setBanner({ kind: "ok", text: "Services saved." });
      setTimeout(() => setBanner(null), 2500);
    } catch {
      setBanner({ kind: "err", text: "Could not save services." });
    }
    setSaving(false);
  };

  const googleServices = services.filter((s) => !s.is_custom);
  const customServices = services.filter((s) => s.is_custom);
  const availablePredefined = predefined.filter((p) => !services.find((s) => s.id === p.id));
  const filteredPredefined = availablePredefined.filter((p) => p.name.toLowerCase().includes(search.toLowerCase()));

  if (loading) return <div className="flex h-full items-center justify-center"><LogoLoader size={32} /></div>;

  return (
    <div className="flex h-full flex-col">
      {/* Sticky Header */}
      <div className="shrink-0 border-b border-ink/[0.06] bg-white/80 px-6 py-4 backdrop-blur dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[18px] font-bold text-ink dark:text-fog">Services</h1>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">
              {selectedLocation ? `${selectedLocation.name} · ${selectedLocation.primary_category}` : "Manage your services"}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="relative">
              <select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value)}
                className="w-56 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog">
                {locations.map((loc) => <option key={loc.id} value={loc.id}>{loc.name}</option>)}
              </select>
              <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <button onClick={() => setShowAdd(true)} className="rounded-xl bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:opacity-90">
              + Add Service
            </button>
            {hasChanges && (
              <button onClick={handleSave} disabled={saving} className="rounded-xl bg-emerald-500 px-4 py-2 text-[13px] font-semibold text-white transition hover:bg-emerald-600 disabled:opacity-50">
                {saving ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : "Save Changes"}
              </button>
            )}
          </div>
        </div>
        {banner && (
          <div className={`mt-3 rounded-lg px-3 py-1.5 text-[12px] font-medium ${banner.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
            {banner.text}
          </div>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-2xl space-y-6">

          {/* Empty state */}
          {services.length === 0 && !showAdd && (
            <div className="flex flex-col items-center rounded-2xl border border-dashed border-ink/[0.12] py-16 dark:border-fog/[0.12]">
              <WrenchIcon className="mb-3 h-10 w-10 text-ink/15 dark:text-fog/15" />
              <p className="text-[14px] font-medium text-ink/40 dark:text-fog/40">No services yet</p>
              <p className="mt-1 text-[12px] text-ink/30 dark:text-fog/30">Add services from Google's predefined list or create custom ones.</p>
              <button onClick={() => setShowAdd(true)} className="mt-4 rounded-xl bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:opacity-90">
                + Add Service
              </button>
            </div>
          )}

          {/* Google Predefined Services */}
          {googleServices.length > 0 && (
            <div>
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <h2 className="text-[14px] font-semibold text-ink dark:text-fog">Google Services</h2>
                  <p className="text-[11px] text-ink/35 dark:text-fog/35">Based on your category: {selectedLocation?.primary_category}</p>
                </div>
                <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[10px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                  {googleServices.filter((s) => s.is_offered).length}/{googleServices.length} offered
                </span>
              </div>
              <div className="space-y-1">
                {googleServices.map((svc) => (
                  <div key={svc.id} className="group flex items-center gap-3 rounded-xl border border-ink/[0.04] bg-white px-4 py-3 transition hover:border-ink/[0.08] dark:border-fog/[0.04] dark:bg-ink dark:hover:border-fog/[0.08]">
                    <button onClick={() => toggleOffered(svc.id)}
                      className={`h-5 w-5 shrink-0 rounded-md border-2 transition ${svc.is_offered ? "border-deep-violet bg-deep-violet" : "border-ink/20 dark:border-fog/20"}`}>
                      {svc.is_offered && (
                        <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" className="h-full w-full p-0.5"><path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      )}
                    </button>
                    <div className="flex-1 min-w-0">
                      <p className={`text-[13px] font-medium ${svc.is_offered ? "text-ink dark:text-fog" : "text-ink/40 dark:text-fog/40"}`}>{svc.name}</p>
                      <p className="text-[10px] text-ink/30 dark:text-fog/30">{svc.category}</p>
                    </div>
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${svc.is_offered ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400" : "bg-ink/[0.04] text-ink/30 dark:bg-fog/[0.04] dark:text-fog/30"}`}>
                      {svc.is_offered ? "Active" : "Not offered"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Custom Services */}
          {customServices.length > 0 && (
            <div>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-[14px] font-semibold text-ink dark:text-fog">Custom Services</h2>
                <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[10px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                  {customServices.filter((s) => s.is_offered).length}/{customServices.length} offered
                </span>
              </div>
              <div className="space-y-1">
                {customServices.map((svc) => (
                  <div key={svc.id} className="group flex items-center gap-3 rounded-xl border border-ink/[0.04] bg-white px-4 py-3 transition hover:border-ink/[0.08] dark:border-fog/[0.04] dark:bg-ink dark:hover:border-fog/[0.08]">
                    <button onClick={() => toggleOffered(svc.id)}
                      className={`h-5 w-5 shrink-0 rounded-md border-2 transition ${svc.is_offered ? "border-deep-violet bg-deep-violet" : "border-ink/20 dark:border-fog/20"}`}>
                      {svc.is_offered && (
                        <svg viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" className="h-full w-full p-0.5"><path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      )}
                    </button>
                    <div className="flex-1 min-w-0">
                      <p className={`text-[13px] font-medium ${svc.is_offered ? "text-ink dark:text-fog" : "text-ink/40 dark:text-fog/40"}`}>{svc.name}</p>
                      <p className="text-[10px] text-ink/30 dark:text-fog/30">{svc.category}</p>
                    </div>
                    <button onClick={() => removeService(svc.id)} className="shrink-0 text-ink/15 transition hover:text-red-500 dark:text-fog/15">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Add Service Modal */}
      {showAdd && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowAdd(false)}>
          <div className="w-full max-w-lg rounded-2xl border border-ink/[0.08] bg-white shadow-2xl dark:border-fog/[0.1] dark:bg-ink" onClick={(e) => e.stopPropagation()}>
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-ink/[0.06] px-5 py-4 dark:border-fog/[0.06]">
              <h2 className="text-[15px] font-bold text-ink dark:text-fog">Add Service</h2>
              <button onClick={() => setShowAdd(false)} className="text-ink/30 transition hover:text-ink/60 dark:text-fog/30">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
              </button>
            </div>

            {/* Tabs */}
            <div className="flex border-b border-ink/[0.06] dark:border-fog/[0.06]">
              <button onClick={() => setAddTab("google")}
                className={`flex-1 py-2.5 text-[13px] font-semibold transition ${addTab === "google" ? "border-b-2 border-deep-violet text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40"}`}>
                Google Services
              </button>
              <button onClick={() => setAddTab("custom")}
                className={`flex-1 py-2.5 text-[13px] font-semibold transition ${addTab === "custom" ? "border-b-2 border-deep-violet text-deep-violet" : "text-ink/40 hover:text-ink/60 dark:text-fog/40"}`}>
                Custom Service
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-5">
              {addTab === "google" ? (
                <div className="space-y-3">
                  <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search services..."
                    className="input-field" autoFocus />
                  <p className="text-[11px] text-ink/30 dark:text-fog/30">
                    Available based on: {selectedLocation?.primary_category}
                  </p>
                  <div className="max-h-64 space-y-1 overflow-y-auto">
                    {filteredPredefined.length === 0 ? (
                      <p className="py-6 text-center text-[12px] text-ink/30 dark:text-fog/30">
                        {search ? "No matching services" : "All available services are already added"}
                      </p>
                    ) : (
                      filteredPredefined.map((svc) => (
                        <button key={svc.id} onClick={() => addPredefined(svc)}
                          className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition hover:bg-deep-violet/[0.04]">
                          <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md border border-ink/15 dark:border-fog/15">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3 w-3 text-ink/20"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
                          </div>
                          <div className="flex-1">
                            <p className="text-[13px] font-medium text-ink dark:text-fog">{svc.name}</p>
                            <p className="text-[10px] text-ink/30 dark:text-fog/30">{svc.category}</p>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-ink/50 dark:text-fog/50">Service Name *</label>
                    <input value={customName} onChange={(e) => setCustomName(e.target.value)} placeholder="e.g. Emergency Repair" className="input-field" autoFocus />
                  </div>
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-ink/50 dark:text-fog/50">Category</label>
                    <input value={customCategory} onChange={(e) => setCustomCategory(e.target.value)} placeholder="e.g. Repair, Consulting" className="input-field" />
                  </div>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="flex justify-end gap-2 border-t border-ink/[0.06] px-5 py-3 dark:border-fog/[0.06]">
              <button onClick={() => setShowAdd(false)} className="btn-secondary">Cancel</button>
              {addTab === "custom" && (
                <button onClick={addCustom} disabled={!customName.trim()} className="btn-primary disabled:opacity-50">Add Service</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function WrenchIcon({ className }: { className?: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" /></svg>;
}
