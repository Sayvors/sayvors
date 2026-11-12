"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

interface LocationOption {
  id: string; // listing/location id
  name: string;
  channelId: string; // google channel id
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
  const [banner, setBanner] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels?limit=100");
        const googleChannels = (data.channels ?? [])
          .filter((channel: { platform: string; status?: string }) => channel.platform === "google_reviews")
          .map((channel: { id: string; display_name: string | null; listing_id?: string | null }) => ({
            id: channel.listing_id ?? channel.id,
            name: channel.display_name ?? "Google location",
            channelId: channel.id,
          }));
        if (!cancelled) {
          setLocations(googleChannels);
          setSelectedChannelId(googleChannels[0]?.channelId ?? null);
        }
      } catch {
        if (!cancelled) setLocations([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedLocation = useMemo(
    () => locations.find((l) => l.channelId === selectedChannelId) ?? null,
    [locations, selectedChannelId]
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

  const removeItem = async (name: string) => {
    if (!selectedChannelId) return;
    try {
      await apiFetch(
        `/api/v1/channels/${encodeURIComponent(selectedChannelId)}/google-media?name=${encodeURIComponent(name)}`,
        { method: "DELETE" }
      );
      setItems((prev) => prev.filter((m) => m.name !== name));
      setBanner("Removed from Google.");
      setTimeout(() => setBanner(null), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 220) : "Could not remove photo.");
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LogoLoader size={28} />
      </div>
    );
  }

  if (locations.length === 0) {
    return (
      <div className="rounded-[2px] border border-dashed border-ink/[0.12] bg-white px-6 py-14 text-center dark:border-fog/[0.12] dark:bg-ink">
        <p className="text-[15px] font-bold text-ink dark:text-fog">No Google locations connected</p>
        <p className="mt-1 text-[12px] text-ink/45 dark:text-fog/45">Connect a Google Business Profile location to see live photos (gallery, banner/cover, profile picture).</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4 px-6 py-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[16px] font-bold text-ink dark:text-fog">Live on Google</h2>
          <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">
            Photos currently on your Google Business Profile for the selected location. Filter by category (Banner/Cover, Profile picture, Exterior, Interior, etc.).
          </p>
        </div>
        <button
          onClick={() => selectedChannelId && loadGallery(selectedChannelId, category)}
          disabled={galleryLoading || !selectedChannelId}
          className="rounded-[2px] border border-ink/[0.08] px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:border-deep-violet/30 disabled:opacity-50 dark:border-fog/[0.1] dark:text-fog/70"
        >
          {galleryLoading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <select
            value={selectedChannelId ?? ""}
            onChange={(e) => setSelectedChannelId(e.target.value || null)}
            className="w-64 max-w-full appearance-none rounded-[2px] border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
          >
            {locations.map((l) => (
              <option key={l.channelId} value={l.channelId}>{l.name}</option>
            ))}
          </select>
          <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {CATEGORY_FILTERS.map((c) => (
            <button
              key={c.value || "all"}
              onClick={() => setCategory(c.value)}
              className={`rounded-full px-3 py-1.5 text-[12px] font-semibold transition ${
                category === c.value
                  ? "bg-deep-violet text-white"
                  : "bg-ink/[0.04] text-ink/65 hover:bg-ink/[0.07] dark:bg-fog/[0.06] dark:text-fog/70"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {banner && <div className="rounded-[2px] bg-emerald-50 px-3 py-2 text-[12px] font-medium text-emerald-700">{banner}</div>}
      {error && <div className="rounded-[2px] border border-red-500/30 bg-red-500/10 px-3 py-2 text-[12px] font-medium text-red-700 dark:text-red-400">{error}</div>}

      {galleryLoading && items.length === 0 ? (
        <div className="flex justify-center py-12"><LogoLoader size={24} /></div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center rounded-[2px] border border-dashed border-ink/[0.12] bg-white py-16 dark:border-fog/[0.12] dark:bg-ink">
          <p className="text-[14px] font-medium text-ink/40 dark:text-fog/40">No live media found</p>
          <p className="mt-1 text-[12px] text-ink/30 dark:text-fog/30">
            {category ? "No photos in this category for the selected location." : "Publish a photo to the Google gallery/profile/banner to see it here."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {items.map((m) => (
            <div key={m.name} className="overflow-hidden rounded-[2px] border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
              <div className="relative flex aspect-[4/3] items-center justify-center bg-ink/[0.03] dark:bg-fog/[0.04]">
                {(m.thumbnailUrl || m.googleUrl) ? (
                  // eslint-disable-next-line @next/next/no-img-element -- Google-hosted media URLs vary
                  <img src={m.thumbnailUrl || m.googleUrl || ""} alt="" className="h-full w-full object-cover" loading="lazy" />
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-8 w-8 text-ink/20 dark:text-fog/20"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></svg>
                )}
                {m.category && (
                  <span className="absolute left-2 top-2 rounded-[2px] bg-black/55 px-2 py-0.5 text-[9px] font-bold text-white">
                    {m.category === "COVER" ? "BANNER" : m.category === "PROFILE" ? "PROFILE" : m.category.replace(/_/g, " ")}
                  </span>
                )}
              </div>
              <div className="space-y-2 p-2.5">
                <p className="truncate text-[12px] font-semibold text-ink dark:text-fog">
                  {m.category === "COVER" ? "Banner (Cover)" : m.category === "PROFILE" ? "Profile picture" : (m.category || "Media").replace(/_/g, " ")}
                </p>
                <p className="truncate text-[10px] text-ink/35 dark:text-fog/35">
                  {m.category === "PROFILE"
                    ? // Google returns the Unix epoch for a profile photo's
                      // createTime and leaves its dimensions empty, so the
                      // date is not the upload date - rendering it printed
                      // "1/1/1970" under every profile picture.
                      (m.mediaFormat || "PHOTO")
                    : m.createTime
                      ? new Date(m.createTime).toLocaleString()
                      : (m.mediaFormat || "PHOTO")}
                </p>
                <button
                  onClick={() => removeItem(m.name)}
                  className="w-full rounded-[2px] border border-red-200 py-1.5 text-[11px] font-semibold text-red-600 hover:bg-red-50"
                >
                  Remove from Google
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
