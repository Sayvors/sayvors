"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type Channel = { id: string; display_name: string | null; status: string };
type Verification = { channel_id: string; status: string; method: string | null; contact_target: string | null; attempts: number; requested_at: string | null; verified_at: string | null; provider_managed: boolean };
type Method = "phone" | "sms" | "email" | "postcard" | "video" | "live_video";

const METHODS: { id: Method; title: string; description: string; timing: string; color: string }[] = [
  { id: "postcard", title: "Postcard", description: "Mail a code to the business address", timing: "5-14 days", color: "violet" },
  { id: "phone", title: "Phone call", description: "Receive an automated verification call", timing: "Instant", color: "emerald" },
  { id: "sms", title: "SMS", description: "Receive a verification code by text", timing: "Instant", color: "sky" },
  { id: "email", title: "Email", description: "Receive a code at a business email", timing: "Instant", color: "violet" },
  { id: "video", title: "Video", description: "Submit a video of the business", timing: "1-3 days", color: "amber" },
  { id: "live_video", title: "Live call", description: "Schedule a call with a provider agent", timing: "Schedule", color: "rose" },
];

export default function VerificationPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [verification, setVerification] = useState<Verification | null>(null);
  const [activeMethod, setActiveMethod] = useState<Method | null>(null);
  const [contactTarget, setContactTarget] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    async function loadChannels() {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const google = (data.channels ?? []).filter((channel: Channel & { platform: string }) => channel.platform === "google_reviews");
        setChannels(google);
        setSelectedId(google[0]?.id ?? "");
      } catch (error) {
        setMessage(error instanceof Error ? error.message : "Could not load channels.");
      } finally {
        setLoading(false);
      }
    }
    void loadChannels();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setVerification(null);
      return;
    }
    void apiFetch(`/api/v1/channels/${selectedId}/verification`)
      .then(setVerification)
      .catch((error) => setMessage(error instanceof Error ? error.message : "Could not load verification status."));
  }, [selectedId]);

  async function requestVerification() {
    if (!selectedId || !activeMethod) return;
    setSaving(true);
    setMessage(null);
    try {
      const next = await apiFetch(`/api/v1/channels/${selectedId}/verification`, {
        method: "POST",
        body: JSON.stringify({ method: activeMethod, contact_target: contactTarget.trim() || null }),
      });
      setVerification(next);
      setMessage("Verification request saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save verification request.");
    } finally {
      setSaving(false);
    }
  }

  const selected = channels.find((channel) => channel.id === selectedId);
  const selectedMethod = METHODS.find((method) => method.id === activeMethod);

  return (
    <div className="h-full overflow-y-auto bg-[#f4f1ff] p-4 sm:p-6">
      <div className="mx-auto max-w-5xl space-y-5">
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div>
            <h1 className="text-[22px] font-bold text-ink dark:text-fog">Verification</h1>
            <p className="mt-1 text-[13px] text-ink/55 dark:text-fog/55">Choose a verification method for your business location.</p>
          </div>
          <span className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${channels.length ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
            {channels.length ? "Google connected" : "Google not connected"}
          </span>
        </div>

        {message && <div className="rounded-xl border border-deep-violet/15 bg-white px-4 py-3 text-[12px] text-ink/70">{message}</div>}

        {loading ? (
          <div className="flex justify-center rounded-3xl bg-white/70 py-24"><LogoLoader size={34} /></div>
        ) : (
          <>
            <section className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.07)]">
              <label className="block text-[11px] font-bold text-ink/55">Business location</label>
              <select value={selectedId} onChange={(event) => setSelectedId(event.target.value)} className="input-field mt-2">
                <option value="">No location selected</option>
                {channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.display_name || "Unnamed location"}</option>)}
              </select>
            </section>

            <section className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.07)]">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-[16px] font-bold text-ink">Verification status</h2>
                  <p className="mt-1 text-[11px] text-ink/45">{selected?.display_name || "No connected location data"}</p>
                </div>
                <span className="rounded-full bg-ink/[0.05] px-3 py-1 text-[10px] font-bold capitalize text-ink/55">{verification?.status || "unstarted"}</span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <Info label="Method" value={verification?.method?.replace("_", " ") || ""} />
                <Info label="Attempts" value={verification ? String(verification.attempts) : ""} />
                <Info label="Requested" value={verification?.requested_at ? new Date(verification.requested_at).toLocaleDateString() : ""} />
              </div>
            </section>

            <section>
              <div className="mb-3"><h2 className="text-[16px] font-bold text-ink">Choose a verification method</h2><p className="mt-1 text-[12px] text-ink/45">Available methods are shown even before location data is connected.</p></div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {METHODS.map((method) => <MethodCard key={method.id} method={method} selected={activeMethod === method.id} disabled={!selectedId} onClick={() => setActiveMethod(method.id)} />)}
              </div>
            </section>

            <section className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.07)]">
              <h2 className="text-[16px] font-bold text-ink">Request details</h2>
              <p className="mt-1 text-[12px] text-ink/45">{selectedMethod?.description || "Select a method above to configure a request."}</p>
              <div className="mt-4 grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
                <label className="text-[11px] font-bold text-ink/55">Contact target <input value={contactTarget} onChange={(event) => setContactTarget(event.target.value)} placeholder="Phone or email, if required" className="input-field mt-1" /></label>
                <button onClick={() => void requestVerification()} disabled={!selectedId || !activeMethod || saving} className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white disabled:cursor-not-allowed disabled:opacity-40">{saving ? "Saving..." : "Request verification"}</button>
              </div>
              <p className="mt-3 text-[11px] text-amber-700">Requests are stored in Sayvors. Verification completion remains provider-managed.</p>
            </section>
          </>
        )}
      </div>
    </div>
  );
}

function MethodCard({ method, selected, disabled, onClick }: { method: typeof METHODS[number]; selected: boolean; disabled: boolean; onClick: () => void }) {
  return <button type="button" disabled={disabled} onClick={onClick} className={`rounded-2xl border p-4 text-left transition ${selected ? "border-deep-violet bg-deep-violet/[0.05] shadow-sm" : "border-white bg-white/80 hover:border-deep-violet/20"} ${disabled ? "cursor-not-allowed opacity-60" : ""}`}><div className="flex items-start justify-between gap-3"><div><div className="text-[13px] font-bold text-ink">{method.title}</div><div className="mt-1 text-[11px] leading-relaxed text-ink/50">{method.description}</div></div><span className="rounded-full bg-ink/[0.05] px-2 py-1 text-[9px] font-bold text-ink/45">{method.timing}</span></div><div className={`mt-4 h-1 rounded-full ${selected ? "bg-deep-violet" : "bg-ink/[0.06]"}`} /></button>;
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl bg-ink/[0.025] p-3"><div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{label}</div><div className="mt-2 min-h-4 text-[12px] text-ink/70">{value || " "}</div></div>;
}
