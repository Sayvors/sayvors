"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

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

  useEffect(() => {
    async function load() {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const google = (data.channels ?? []).filter((channel: Channel & { platform: string }) => channel.platform === "google_reviews");
        setChannels(google); setSelectedId(google[0]?.id ?? "");
      } catch (error) { setMessage(error instanceof Error ? error.message : "Could not load channels."); }
      finally { setLoading(false); }
    }
    void load();
  }, []);

  async function loadServices(channelId: string) {
    if (!channelId) return;
    try { const data = await apiFetch(`/api/v1/channels/${channelId}/services`); setServices(data.services ?? []); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not load services."); }
  }

  useEffect(() => { void loadServices(selectedId); }, [selectedId]);

  async function addService() {
    if (!name.trim() || !selectedId) return;
    setSaving(true); setMessage(null);
    try { const created = await apiFetch(`/api/v1/channels/${selectedId}/services`, { method: "POST", body: JSON.stringify({ name: name.trim(), category: category.trim() || "Custom", description: description.trim() || null, source: "custom", is_offered: true }) }); setServices((current) => [...current, created]); setName(""); setDescription(""); setMessage("Service saved."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not save service."); }
    finally { setSaving(false); }
  }

  async function toggleService(service: Service) {
    try { const updated = await apiFetch(`/api/v1/channels/${selectedId}/services/${service.id}`, { method: "PUT", body: JSON.stringify({ is_offered: !service.is_offered }) }); setServices((current) => current.map((item) => item.id === updated.id ? updated : item)); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not update service."); }
  }

  async function removeService(id: string) {
    try { await apiFetch(`/api/v1/channels/${selectedId}/services/${id}`, { method: "DELETE" }); setServices((current) => current.filter((item) => item.id !== id)); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not delete service."); }
  }

  const selected = channels.find((channel) => channel.id === selectedId);
  return <div className="h-full overflow-y-auto bg-[#f4f1ff] p-4 sm:p-6"><div className="mx-auto max-w-4xl space-y-5">
    <div className="flex items-center justify-between gap-3"><div><h1 className="text-[22px] font-bold text-ink">Services</h1><p className="mt-1 text-[13px] text-ink/55">Manage services for a connected Google channel.</p></div><Link href="/dashboard/channels" className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white">Manage connections</Link></div>
    {loading ? <div className="flex justify-center rounded-3xl bg-white/70 py-24"><LogoLoader size={34} /></div> : channels.length === 0 ? <div className="rounded-3xl border border-dashed border-ink/15 bg-white/70 px-6 py-20 text-center"><h2 className="text-[18px] font-bold text-ink">No Google channel connected</h2><p className="mt-2 text-[13px] text-ink/50">Connect Google Business Profile first.</p></div> : <>
      <div className="rounded-3xl border border-white bg-white/80 p-5"><label className="block text-[11px] font-bold text-ink/55">Google location<select value={selectedId} onChange={(event) => setSelectedId(event.target.value)} className="input-field mt-2">{channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || "Unnamed location"}</option>)}</select></label></div>
      <div className="rounded-3xl border border-white bg-white/80 p-5"><h2 className="text-[15px] font-bold text-ink">Add service</h2><div className="mt-4 grid gap-3 sm:grid-cols-3"><input value={name} onChange={(event) => setName(event.target.value)} placeholder="Service name" className="input-field" /><input value={category} onChange={(event) => setCategory(event.target.value)} placeholder="Category" className="input-field" /><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" className="input-field" /></div><button onClick={() => void addService()} disabled={saving || !name.trim()} className="mt-4 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white disabled:opacity-50">{saving ? "Saving..." : "Add service"}</button></div>
      <div className="space-y-2">{services.length === 0 ? <div className="rounded-3xl bg-white/70 p-10 text-center text-[13px] text-ink/50">No services saved yet.</div> : services.map((service) => <div key={service.id} className="flex items-center gap-3 rounded-2xl border border-white bg-white/80 p-4"><button onClick={() => void toggleService(service)} className={`h-5 w-5 rounded-md border-2 ${service.is_offered ? "border-deep-violet bg-deep-violet" : "border-ink/20"}`} aria-label="Toggle offered status">{service.is_offered && <span className="text-[11px] text-white">✓</span>}</button><div className="min-w-0 flex-1"><div className="text-[13px] font-bold text-ink">{service.name}</div><div className="text-[11px] text-ink/45">{service.category} · {service.is_offered ? "Offered" : "Not offered"}{service.description ? ` · ${service.description}` : ""}</div></div><button onClick={() => void removeService(service.id)} className="text-[11px] font-semibold text-red-500">Delete</button></div>)}</div>
    </>}
    {message && <div className="rounded-xl border border-deep-violet/15 bg-white px-4 py-3 text-[12px] text-ink/70">{message}</div>}
  </div></div>;
}
