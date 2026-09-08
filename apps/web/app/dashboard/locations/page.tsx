"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type Channel = {
  id: string;
  platform: string;
  platform_user_id: string | null;
  display_name: string | null;
  status: string;
  avatar_url: string | null;
  created_at: string;
};

export default function LocationsPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadChannels() {
      try {
        const data = await apiFetch("/api/v1/channels/?limit=100");
        if (cancelled) return;
        const googleChannels = (data.channels ?? []).filter((channel: Channel) => channel.platform === "google_reviews");
        setChannels(googleChannels);
        setSelectedId(googleChannels[0]?.id ?? null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load connected locations.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadChannels();
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = channels.find((channel) => channel.id === selectedId) ?? null;

  return (
    <div className="h-full overflow-y-auto bg-[#f4f1ff] p-4 sm:p-6">
      <div className="mx-auto max-w-6xl space-y-5">
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div>
            <h1 className="text-[22px] font-bold text-ink dark:text-fog">Locations</h1>
            <p className="mt-1 text-[13px] text-ink/55 dark:text-fog/55">
              Connected Google Business locations from your active channels.
            </p>
          </div>
          <Link
            href="/dashboard/channels"
            className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md shadow-deep-violet/20 transition hover:bg-deep-violet/90"
          >
            Manage connections
          </Link>
        </div>

        {loading ? (
          <div className="flex justify-center rounded-3xl bg-white/70 py-24"><LogoLoader size={34} /></div>
        ) : error ? (
          <div className="rounded-3xl border border-red-200 bg-red-50 p-8 text-center">
            <p className="text-[13px] font-semibold text-red-700">Could not load connected locations</p>
            <p className="mt-1 text-[12px] text-red-600/70">{error}</p>
          </div>
        ) : channels.length === 0 ? (
          <div className="rounded-3xl border border-dashed border-ink/15 bg-white/70 px-6 py-20 text-center">
            <LocationIcon className="mx-auto h-11 w-11 text-deep-violet/35" />
            <h2 className="mt-4 text-[18px] font-bold text-ink">No Google locations connected</h2>
            <p className="mx-auto mt-2 max-w-md text-[13px] text-ink/50">
              Connect Google Business Profile from Channels. Connected Google locations will appear here automatically.
            </p>
            <Link href="/dashboard/channels" className="mt-5 inline-flex rounded-xl bg-deep-violet px-5 py-2.5 text-[12px] font-bold text-white">Connect Google</Link>
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-[270px_1fr]">
            <aside className="h-fit rounded-3xl border border-white bg-white/75 p-3 shadow-[0_12px_30px_rgba(58,39,120,0.07)]">
              <div className="px-2 pb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40">Connected locations</div>
              <div className="space-y-1">
                {channels.map((channel) => (
                  <button
                    key={channel.id}
                    type="button"
                    onClick={() => setSelectedId(channel.id)}
                    className={`w-full rounded-2xl px-3 py-3 text-left transition ${selected?.id === channel.id ? "bg-deep-violet text-white" : "text-ink/70 hover:bg-ink/[0.04]"}`}
                  >
                    <span className="block truncate text-[13px] font-bold">{channel.display_name || "Unnamed Google location"}</span>
                    <span className={`mt-1 block text-[10px] capitalize ${selected?.id === channel.id ? "text-white/65" : "text-ink/45"}`}>{channel.status}</span>
                  </button>
                ))}
              </div>
            </aside>

            {selected && (
              <section className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.07)] sm:p-6">
                <div className="flex items-start justify-between gap-3 border-b border-ink/[0.06] pb-5">
                  <div>
                    <div className="flex items-center gap-2">
                      <LocationIcon className="h-5 w-5 text-deep-violet" />
                      <h2 className="text-[20px] font-bold text-ink">{selected.display_name || "Unnamed Google location"}</h2>
                    </div>
                    <p className="mt-2 text-[12px] text-ink/50">Google Business connection</p>
                  </div>
                  <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold capitalize ${selected.status === "active" ? "bg-emerald-100 text-emerald-700" : "bg-ink/[0.06] text-ink/50"}`}>{selected.status}</span>
                </div>

                <div className="mt-5 grid gap-3 sm:grid-cols-2">
                  <Info label="Channel ID" value={selected.id} />
                  <Info label="Google account ID" value={selected.platform_user_id || "Unavailable from current API"} />
                  <Info label="Connected on" value={new Date(selected.created_at).toLocaleString()} />
                  <Info label="Address and business details" value="Unavailable from current channels API" />
                </div>

                <div className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-[12px] text-amber-800">
                  Detailed location editing is intentionally unavailable until the backend exposes an authoritative Location API. This page currently shows only data returned by the existing Channels API.
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return <div className="rounded-2xl bg-ink/[0.025] p-3"><div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">{label}</div><div className="mt-2 break-all text-[12px] text-ink/70">{value}</div></div>;
}

function LocationIcon({ className }: { className?: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}><path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0118 0Z" /><circle cx="12" cy="10" r="3" /></svg>;
}
