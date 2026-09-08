"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type Channel = { id: string; display_name: string | null; status: string };
type Verification = { channel_id: string; status: string; method: string | null; contact_target: string | null; attempts: number; requested_at: string | null; verified_at: string | null; provider_managed: boolean };
const METHODS = ["phone", "sms", "email", "postcard", "video", "live_video"] as const;

export default function VerificationPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [verification, setVerification] = useState<Verification | null>(null);
  const [method, setMethod] = useState<(typeof METHODS)[number]>("email");
  const [contactTarget, setContactTarget] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const google = (data.channels ?? []).filter((channel: Channel & { platform: string }) => channel.platform === "google_reviews");
        setChannels(google);
        setSelectedId(google[0]?.id ?? "");
      } catch (error) { setMessage(error instanceof Error ? error.message : "Could not load channels."); }
      finally { setLoading(false); }
    }
    void load();
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    void apiFetch(`/api/v1/channels/${selectedId}/verification`).then(setVerification).catch((error) => setMessage(error instanceof Error ? error.message : "Could not load verification status."));
  }, [selectedId]);

  async function requestVerification() {
    setSaving(true); setMessage(null);
    try {
      const next = await apiFetch(`/api/v1/channels/${selectedId}/verification`, { method: "POST", body: JSON.stringify({ method, contact_target: contactTarget || null }) });
      setVerification(next); setMessage("Verification request saved.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save verification request."); }
    finally { setSaving(false); }
  }

  const selected = channels.find((channel) => channel.id === selectedId);
  return <div className="h-full overflow-y-auto bg-[#f4f1ff] p-4 sm:p-6"><div className="mx-auto max-w-4xl space-y-5">
    <div className="flex items-center justify-between gap-3"><div><h1 className="text-[22px] font-bold text-ink">Verification</h1><p className="mt-1 text-[13px] text-ink/55">Track Sayvors verification requests for connected Google channels.</p></div><Link href="/dashboard/channels" className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white">Manage connections</Link></div>
    {loading ? <div className="flex justify-center rounded-3xl bg-white/70 py-24"><LogoLoader size={34} /></div> : channels.length === 0 ? <div className="rounded-3xl border border-dashed border-ink/15 bg-white/70 px-6 py-20 text-center"><h2 className="text-[18px] font-bold text-ink">No Google channel connected</h2><p className="mt-2 text-[13px] text-ink/50">Connect Google Business Profile first.</p></div> : <>
      <div className="rounded-3xl border border-white bg-white/80 p-5"><label className="block text-[11px] font-bold text-ink/55">Google location</label><select value={selectedId} onChange={(event) => setSelectedId(event.target.value)} className="input-field mt-2"><option value="">Select a channel</option>{channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || "Unnamed location"}</option>)}</select></div>
      {selected && <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.07)]"><div className="flex items-center justify-between"><div><h2 className="text-[17px] font-bold text-ink">{selected.display_name || "Unnamed location"}</h2><p className="mt-1 text-[11px] text-ink/45">Current request: {verification?.status ?? "unstarted"}</p></div><span className="rounded-full bg-ink/[0.05] px-3 py-1 text-[10px] font-bold capitalize text-ink/55">{verification?.method?.replace("_", " ") ?? "Not requested"}</span></div><div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="text-[11px] font-bold text-ink/55">Method<select value={method} onChange={(event) => setMethod(event.target.value as (typeof METHODS)[number])} className="input-field mt-1">{METHODS.map((item) => <option key={item} value={item}>{item.replace("_", " ")}</option>)}</select></label><label className="text-[11px] font-bold text-ink/55">Contact target (optional)<input value={contactTarget} onChange={(event) => setContactTarget(event.target.value)} className="input-field mt-1" placeholder="Phone or email" /></label></div><button onClick={() => void requestVerification()} disabled={saving} className="mt-5 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white disabled:opacity-50">{saving ? "Saving..." : "Request verification"}</button><p className="mt-3 text-[11px] text-amber-700">This records the request in Sayvors. Google verification completion remains provider-managed.</p></div>}
    </>}
    {message && <div className="rounded-xl border border-deep-violet/15 bg-white px-4 py-3 text-[12px] text-ink/70">{message}</div>}
  </div></div>;
}
