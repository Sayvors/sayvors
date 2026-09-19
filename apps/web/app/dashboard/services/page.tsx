"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

const ALL_BRANCHES = "__all__";

type Channel = { id: string; display_name: string | null };
type Service = { id: string; channel_id: string; name: string; category: string; description: string | null; is_offered: boolean; source: string };

export default function ServicesPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [services, setServices] = useState<Service[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("Custom");
  const [description, setDescription] = useState("");
  const [addTarget, setAddTarget] = useState("");

  const isAll = selectedId === ALL_BRANCHES;
  const branchNames: Record<string, string> = Object.fromEntries(channels.map((c) => [c.id, c.display_name || "Unnamed location"]));
  // In "All branches" mode new services need an explicit home branch.
  const addChannelId = isAll ? (addTarget || channels[0]?.id || "") : selectedId;

  useEffect(() => {
    async function load() {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const google = (data.channels ?? []).filter((channel: Channel & { platform: string }) => channel.platform === "google_reviews");
        setChannels(google); setSelectedId(google.length ? ALL_BRANCHES : "");
      } catch (error) { setMessage(error instanceof Error ? error.message : "Could not load channels."); }
      finally { setLoading(false); }
    }
    void load();
  }, []);

  async function loadServices(scopeId: string, list: Channel[]) {
    const targets = scopeId === ALL_BRANCHES ? list : list.filter((c) => c.id === scopeId);
    if (targets.length === 0) { setServices([]); return; }
    try {
      const lists = await Promise.all(targets.map(async (c) => {
        try { const data = await apiFetch(`/api/v1/channels/${c.id}/services`); return (data.services ?? []) as Service[]; }
        catch { return [] as Service[]; }
      }));
      setServices(lists.flat());
    }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not load services."); }
  }

  useEffect(() => { void loadServices(selectedId, channels); }, [selectedId, channels]);

  async function addService() {
    if (!name.trim() || !addChannelId) return;
    setSaving(true); setMessage(null);
    try { const created = await apiFetch(`/api/v1/channels/${addChannelId}/services`, { method: "POST", body: JSON.stringify({ name: name.trim(), category: category.trim() || "Custom", description: description.trim() || null, source: "custom", is_offered: true }) }); setServices((current) => [...current, created]); setName(""); setDescription(""); setMessage("Service saved."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not save service."); }
    finally { setSaving(false); }
  }

  async function toggleService(service: Service) {
    try { const updated = await apiFetch(`/api/v1/channels/${service.channel_id}/services/${service.id}`, { method: "PUT", body: JSON.stringify({ is_offered: !service.is_offered }) }); setServices((current) => current.map((item) => item.id === updated.id ? updated : item)); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not update service."); }
  }

  async function removeService(service: Service) {
    try { await apiFetch(`/api/v1/channels/${service.channel_id}/services/${service.id}`, { method: "DELETE" }); setServices((current) => current.filter((item) => item.id !== service.id)); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not delete service."); }
  }

  return (
    <div className="h-full overflow-y-auto bg-[#f4f1ff] p-4 sm:p-6">
      <div className="mx-auto max-w-4xl space-y-5">
        <PageHeader connected={channels.length > 0} />
        {loading ? (
          <div className="flex justify-center rounded-3xl bg-white/70 py-24"><LogoLoader size={34} /></div>
        ) : (
          <>
            <LocationPicker
              selectedId={selectedId}
              channels={channels}
              onChange={(id) => { setSelectedId(id); setAddTarget(""); }}
            />
            <StatsRow services={services} />
            <AddServiceForm
              name={name} category={category} description={description}
              onName={setName} onCategory={setCategory} onDescription={setDescription}
              isAll={isAll} channels={channels} addTarget={addTarget}
              onAddTarget={setAddTarget} saving={saving}
              canSave={!!name.trim() && !!addChannelId}
              onAdd={() => void addService()}
            />
            <ServiceGroup title="Google services" source="google" services={services.filter((service) => service.source === "google")} onToggle={toggleService} onDelete={removeService} branchNames={isAll ? branchNames : undefined} />
            <ServiceGroup title="Custom services" source="custom" services={services.filter((service) => service.source !== "google")} onToggle={toggleService} onDelete={removeService} branchNames={isAll ? branchNames : undefined} />
          </>
        )}
        {message && <div className="rounded-xl border border-deep-violet/15 bg-white px-4 py-3 text-[12px] text-ink/70">{message}</div>}
      </div>
    </div>
  );
}

function PageHeader({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <h1 className="text-[22px] font-bold text-ink">Services</h1>
        <p className="mt-1 text-[13px] text-ink/55">Manage services for a connected Google channel.</p>
      </div>
      <span className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${connected ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
        {connected ? "Google connected" : "Google not connected"}
      </span>
    </div>
  );
}

function LocationPicker({ selectedId, channels, onChange }: {
  selectedId: string;
  channels: Channel[];
  onChange: (id: string) => void;
}) {
  return (
    <div className="rounded-3xl border border-white bg-white/80 p-5">
      <label className="block text-[11px] font-bold text-ink/55">
        Google location
        <select value={selectedId} onChange={(event) => onChange(event.target.value)} className="input-field mt-2">
          <option value="">No location data</option>
          {channels.length > 0 && <option value={ALL_BRANCHES}>All branches ({channels.length})</option>}
          {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || "Unnamed location"}</option>)}
        </select>
      </label>
    </div>
  );
}

function StatsRow({ services }: { services: Service[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <Stat label="Total services" value={services.length} />
      <Stat label="Offered" value={services.filter((service) => service.is_offered).length} />
      <Stat label="Custom" value={services.filter((service) => service.source === "custom").length} />
    </div>
  );
}

function AddServiceForm({ name, category, description, onName, onCategory, onDescription, isAll, channels, addTarget, onAddTarget, saving, canSave, onAdd }: {
  name: string; category: string; description: string;
  onName: (v: string) => void; onCategory: (v: string) => void; onDescription: (v: string) => void;
  isAll: boolean; channels: Channel[]; addTarget: string;
  onAddTarget: (v: string) => void; saving: boolean; canSave: boolean;
  onAdd: () => void;
}) {
  return (
    <div className="rounded-3xl border border-white bg-white/80 p-5">
      <h2 className="text-[15px] font-bold text-ink">Add service</h2>
      <p className="mt-1 text-[11px] text-ink/45">Service fields remain ready for connected Google location data.</p>
      {isAll && channels.length > 0 && (
        <label className="mt-3 block text-[11px] font-bold text-ink/55">
          Save to branch
          <select value={addTarget || channels[0].id} onChange={(event) => onAddTarget(event.target.value)} className="input-field mt-2">
            {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || "Unnamed location"}</option>)}
          </select>
        </label>
      )}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <input value={name} onChange={(event) => onName(event.target.value)} placeholder="Service name" className="input-field" />
        <input value={category} onChange={(event) => onCategory(event.target.value)} placeholder="Category" className="input-field" />
        <input value={description} onChange={(event) => onDescription(event.target.value)} placeholder="Description" className="input-field" />
      </div>
      <button onClick={onAdd} disabled={saving || !canSave} className="mt-4 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white disabled:opacity-40">
        {saving ? "Saving..." : "Add service"}
      </button>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-2xl border border-white bg-white/80 p-4"><div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{label}</div><div className="mt-2 text-[22px] font-bold text-ink">{value}</div></div>;
}

function ServiceGroup({ title, source, services, onToggle, onDelete, branchNames }: { title: string; source: "google" | "custom"; services: Service[]; onToggle: (service: Service) => Promise<void>; onDelete: (service: Service) => Promise<void>; branchNames?: Record<string, string> }) {
  return <section className="overflow-hidden rounded-3xl border border-white bg-white/80"><header className="flex items-center justify-between border-b border-ink/[0.05] px-4 py-3"><div><h2 className="text-[14px] font-bold text-ink">{title}</h2><p className="mt-0.5 text-[11px] text-ink/40">{source === "google" ? "Google-provided services" : "Services defined by your business"}</p></div><span className="rounded-full bg-ink/[0.04] px-2.5 py-1 text-[10px] font-semibold text-ink/45">{services.length}</span></header>{services.length === 0 ? <div className="border-dashed px-4 py-8 text-center text-[12px] text-ink/35">No service data yet.</div> : <div className="divide-y divide-ink/[0.04]">{services.map((service) => <div key={service.id} className="flex items-center gap-3 px-4 py-3"><button onClick={() => void onToggle(service)} className={`h-5 w-5 rounded-md border-2 ${service.is_offered ? "border-deep-violet bg-deep-violet" : "border-ink/20"}`} aria-label="Toggle offered status">{service.is_offered && <span className="text-[11px] text-white">✓</span>}</button><div className="min-w-0 flex-1"><div className="text-[13px] font-bold text-ink">{service.name}</div><div className="text-[11px] text-ink/45">{branchNames?.[service.channel_id] ? `${branchNames[service.channel_id]} · ` : ""}{service.category} · {service.is_offered ? "Offered" : "Not offered"}{service.description ? ` · ${service.description}` : ""}</div></div><button onClick={() => void onDelete(service)} className="text-[11px] font-semibold text-red-500">Delete</button></div>)}</div>}</section>;
}
