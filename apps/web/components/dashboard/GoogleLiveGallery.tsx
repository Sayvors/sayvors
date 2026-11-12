"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import Modal from "@/components/dashboard/media/Modal";

interface LocationOption {
  id: string;
  name: string;
  channelId: string;
}

interface GoogleGalleryItem {
  name: string;
  mediaFormat?: string | null;
  category?: string | null;
  googleUrl?: string | null;
  thumbnailUrl?: string | null;
  description?: string | null;
  createTime?: string | null;
}

const CATEGORY_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All categories" },
  { value: "COVER", label: "Banner (Cover)" },
  { value: "PROFILE", label: "Profile picture" },
  { value: "EXTERIOR", label: "Exterior" },
  { value: "INTERIOR", label: "Interior" },
  { value: "PRODUCT", label: "Product" },
  { value: "AT_WORK", label: "At work" },
  { value: "FOOD_AND_DRINK", label: "Food & drink" },
  { value: "MENU", label: "Menu" },
  { value: "COMMON_AREA", label: "Common area" },
  { value: "ROOMS", label: "Rooms" },
  { value: "TEAMS", label: "Teams" },
  { value: "ADDITIONAL", label: "Additional" },
];

export default function GoogleLiveGallery() {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedChannelId, setSelectedChannelId] = useState<string | null>(null);
  const [category, setCategory] = useState<string>("");
  const [items, setItems] = useState<GoogleGalleryItem[]>([]);
  const [galleryLoading, setGalleryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmRemove, setConfirmRemove] = useState<{ names: string[] } | null>(null);
  const [removing, setRemoving] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels?limit=100");
        const googleChannels = (data.channels ?? [])
          .filter((channel: { platform: string }) => channel.platform === "google_reviews")
          .map((channel: { id: string; display_name: string | null; listing_id?: string | null }) => ({
            id: channel.listing_id ?? channel.id,
            name: channel.display_name ?? "Google location",
            channelId: channel.id,
          }));
        if (cancelled) return;
        setLocations(googleChannels);
        setSelectedChannelId(googleChannels[0]?.channelId ?? null);
      } catch {
        if (!cancelled) setLocations([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const selectedLocation = useMemo(
    () => locations.find((l) => l.channelId === selectedChannelId) ?? null,
    [locations, selectedChannelId],
  );

  const loadGallery = async (channelId: string, cat: string) => {
    setGalleryLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ page_size: "2500" });
      if (cat) q.set("category", cat);
      const data = await apiFetch(`/api/v1/channels/${encodeURIComponent(channelId)}/google-media?${q.toString()}`);
      const list = Array.isArray(data?.media) ? data.media : [];
      setItems(list as GoogleGalleryItem[]);
      setLastRefresh(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 220) : "Could not load Google gallery.");
      setItems([]);
    } finally {
      setGalleryLoading(false);
    }
  };

  useEffect(() => {
    if (!selectedChannelId) return;
    void loadGallery(selectedChannelId, category);
  }, [selectedChannelId, category]);

  const categoryCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const it of items) {
      const key = (it.category || "").toUpperCase();
      m.set(key, (m.get(key) ?? 0) + 1);
    }
    return m;
  }, [items]);

  const removeOne = async (name: string) => {
    if (!selectedChannelId) return;
    try {
      await apiFetch(
        `/api/v1/channels/${encodeURIComponent(selectedChannelId)}/google-media?name=${encodeURIComponent(name)}`,
        { method: "DELETE" },
      );
      setItems((prev) => prev.filter((m) => m.name !== name));
      setNotice("Removed from Google.");
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 220) : "Could not remove photo.");
    }
  };

  const removeMany = async (names: string[]) => {
    if (!selectedChannelId) return;
    setRemoving(true);
    let ok = 0, fail = 0;
    for (const name of names) {
      try {
        await apiFetch(
          `/api/v1/channels/${encodeURIComponent(selectedChannelId)}/google-media?name=${encodeURIComponent(name)}`,
          { method: "DELETE" },
        );
        ok++;
      } catch {
        fail++;
      }
    }
    await loadGallery(selectedChannelId, category);
    setRemoving(false);
    setConfirmRemove(null);
    setSelected(new Set());
    setSelectionMode(false);
    if (fail === 0) setNotice(`Removed ${ok} photo${ok === 1 ? "" : "s"} from Google.`);
    else setError(`${ok} removed, ${fail} failed.`);
  };

  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(null), 4000);
    return () => clearTimeout(t);
  }, [notice]);

  if (loading) {
    return <div className="flex h-64 items-center justify-center"><LogoLoader size={28} /></div>;
  }

  if (locations.length === 0) {
    return (
      <div className="rounded-[32px] border border-dashed border-ink/15 bg-white p-10 text-center shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)]">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-deep-violet/10 text-[24px]">📍</div>
        <h3 className="mt-4 text-[17px] font-bold text-ink">No Google locations connected</h3>
        <p className="mt-1 text-[13px] text-ink/55">Connect a Google Business Profile location to see live photos.</p>
        <a href="/dashboard/channels" className="mt-5 inline-flex rounded-[20px] bg-deep-violet px-5 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90">Connect Google</a>
      </div>
    );
  }

  const selectedNames = Array.from(selected);

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[20px] font-bold text-ink dark:text-fog">Live on Google</h2>
          <p className="mt-0.5 text-[13px] text-ink/55 dark:text-fog/55">
            Photos currently on your Google Business Profile. Filter by category to find what you need.
            {lastRefresh && <span className="ml-2 text-[11.5px] text-ink/40">· Updated {lastRefresh.toLocaleTimeString()}</span>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!selectionMode ? (
            <button
              type="button"
              onClick={() => setSelectionMode(true)}
              disabled={items.length === 0}
              className="rounded-[20px] border border-ink/10 bg-white px-4 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05] disabled:opacity-40 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:bg-white/[0.04] dark:text-fog"
            >
              Select
            </button>
          ) : (
            <button
              type="button"
              onClick={() => { setSelectionMode(false); setSelected(new Set()); }}
              className="rounded-[20px] border border-ink/10 bg-white px-4 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:bg-white/[0.04] dark:text-fog"
            >
              Cancel
            </button>
          )}
          <button
            type="button"
            onClick={() => selectedChannelId && loadGallery(selectedChannelId, category)}
            disabled={galleryLoading || !selectedChannelId}
            className="rounded-[20px] border border-ink/10 bg-white px-4 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05] disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:bg-white/[0.04] dark:text-fog"
          >
            {galleryLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <select
            value={selectedChannelId ?? ""}
            onChange={(e) => setSelectedChannelId(e.target.value || null)}
            className="w-64 max-w-full appearance-none rounded-[20px] border border-ink/10 bg-white py-2.5 pl-4 pr-9 text-[13px] font-semibold text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
          >
            {locations.map((l) => <option key={l.channelId} value={l.channelId}>{l.name}</option>)}
          </select>
          <svg className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {CATEGORY_FILTERS.map((c) => {
            const count = c.value ? (categoryCounts.get(c.value) ?? 0) : items.length;
            const active = category === c.value;
            return (
              <button
                key={c.value || "all"}
                type="button"
                onClick={() => setCategory(c.value)}
                className={`rounded-full px-3 py-1.5 text-[12px] font-bold transition ${active ? "bg-deep-violet text-white" : "bg-ink/[0.04] text-ink/65 hover:bg-ink/[0.08] dark:bg-white/[0.06] dark:text-fog/70"}`}
              >
                {c.label} <span className={active ? "opacity-80" : "opacity-60"}>({count})</span>
              </button>
            );
          })}
        </div>
      </div>

      {notice && (
        <div className="flex items-start justify-between gap-3 rounded-[20px] bg-emerald-50 px-4 py-3 text-[13px] font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
          <p>{notice}</p>
          <button type="button" onClick={() => setNotice(null)} className="shrink-0 text-[16px] leading-none opacity-60 hover:opacity-100" aria-label="Dismiss">×</button>
        </div>
      )}
      {error && (
        <div className="flex items-center justify-between rounded-[20px] border border-red-500/40 bg-red-500/10 px-4 py-3 text-[13px] text-red-700 dark:text-red-300">
          <span>{error}</span>
          <button type="button" onClick={() => selectedChannelId && loadGallery(selectedChannelId, category)} className="rounded-[16px] border border-red-500/40 px-3 py-1 text-[12px] font-bold">Retry</button>
        </div>
      )}

      {galleryLoading && items.length === 0 ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => <div key={i} className="aspect-[4/3] animate-pulse rounded-[24px] bg-ink/[0.06]" />)}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center rounded-[32px] border border-dashed border-ink/15 bg-white p-12 text-center shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)]">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-deep-violet/10 text-[24px]">📷</div>
          <h3 className="mt-4 text-[17px] font-bold text-ink">No live media found</h3>
          <p className="mt-1 max-w-sm text-[13px] text-ink/55">
            {category ? "No photos in this category for the selected location." : "Publish a photo to the gallery, profile or cover to see it here."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((m) => {
            const isSelected = selected.has(m.name);
            const isProfile = m.category === "PROFILE";
            return (
              <div
                key={m.name}
                className={`group relative overflow-hidden rounded-[24px] border bg-white shadow-[0_12px_28px_-20px_rgba(20,16,31,0.35)] transition hover:-translate-y-0.5 hover:shadow-[0_20px_40px_-22px_rgba(20,16,31,0.5)] ${isSelected ? "ring-2 ring-deep-violet" : "ring-1 ring-ink/[0.06]"}`}
              >
                <div className="relative aspect-[4/3] overflow-hidden bg-ink/[0.04]">
                  {m.thumbnailUrl || m.googleUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element -- Google-hosted media URLs vary
                    <img src={m.thumbnailUrl || m.googleUrl || ""} alt="" className="h-full w-full object-cover" loading="lazy" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-[32px] text-ink/20">🖼</div>
                  )}
                  {m.category && (
                    <span className="absolute left-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">
                      {m.category === "COVER" ? "Banner" : m.category === "PROFILE" ? "Profile" : m.category.replace(/_/g, " ")}
                    </span>
                  )}
                  {selectionMode && (
                    <label className="absolute right-2 top-2 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full bg-white/95 shadow ring-1 ring-ink/10" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => setSelected((prev) => {
                          const next = new Set(prev);
                          if (next.has(m.name)) next.delete(m.name); else next.add(m.name);
                          return next;
                        })}
                        className="h-4 w-4 accent-deep-violet"
                        aria-label="Select photo"
                      />
                    </label>
                  )}
                </div>
                <div className="space-y-1 p-3">
                  <p className="truncate text-[12.5px] font-bold text-ink dark:text-fog">
                    {m.category === "COVER" ? "Banner (Cover)" : m.category === "PROFILE" ? "Profile picture" : (m.category || "Media").replace(/_/g, " ")}
                  </p>
                  <p className="truncate text-[11px] text-ink/50 dark:text-fog/50">
                    {isProfile
                      ? (m.mediaFormat || "Photo")
                      : m.createTime
                      ? new Date(m.createTime).toLocaleString()
                      : (m.mediaFormat || "Photo")}
                  </p>
                </div>
                {!selectionMode && (
                  <div className="px-3 pb-3">
                    <button
                      type="button"
                      onClick={() => setConfirmRemove({ names: [m.name] })}
                      className="w-full rounded-[16px] border border-red-200 bg-white px-3 py-1.5 text-[11.5px] font-bold text-red-600 transition hover:bg-red-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-red-400/40"
                    >
                      Remove from Google
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {selectionMode && selected.size > 0 && (
        <div className="sticky bottom-3 z-10 mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 rounded-[24px] border border-ink/10 bg-white px-4 py-3 shadow-[0_24px_48px_-24px_rgba(20,16,31,0.6)]">
          <span className="text-[13px] font-bold text-ink">{selected.size} selected</span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setConfirmRemove({ names: selectedNames })}
              disabled={removing}
              className="rounded-[16px] border border-red-300 bg-white px-4 py-2 text-[12px] font-bold text-red-600 transition hover:bg-red-50 disabled:opacity-50"
            >
              Remove ({selected.size})
            </button>
          </div>
        </div>
      )}

      {confirmRemove && (
        <Modal open onClose={() => setConfirmRemove(null)} title={`Remove ${confirmRemove.names.length === 1 ? "this photo" : `${confirmRemove.names.length} photos`} from Google?`} subtitle="This removes them from your Google Business Profile. This cannot be undone." busy={removing} width="max-w-[440px]">
          <div className="space-y-4">
            <p className="text-[13px] text-ink/65">
              {confirmRemove.names.length === 1 ? "The photo will be removed from Google." : `${confirmRemove.names.length} photos will be removed from Google.`}
            </p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setConfirmRemove(null)} disabled={removing} className="rounded-[20px] border border-ink/10 bg-white px-5 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05] disabled:opacity-50">Keep them</button>
              <button type="button" onClick={() => removeMany(confirmRemove.names)} disabled={removing} className="rounded-[20px] bg-red-600 px-5 py-2.5 text-[13px] font-bold text-white transition hover:bg-red-700 disabled:opacity-60">
                {removing ? "Removing…" : "Remove"}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
