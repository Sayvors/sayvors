"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type MediaType = "PHOTO" | "VIDEO";
type MediaSource = "OWN" | "CUSTOMER";
type MediaTab = "all" | "photos" | "videos" | "customer" | "scheduled";
type MediaStatus = "DRAFT" | "SCHEDULED" | "PUBLISHED" | "FAILED";

interface MediaItem {
  id: string;
  type: MediaType;
  source: MediaSource;
  category: string;
  thumbnailUrl?: string;
  sourceUrl?: string;
  views: number;
  attribution?: string;
  createdAt: string;
  isProfile?: boolean;
  isCover?: boolean;
  status?: MediaStatus;
  scheduledAt?: string;
  error?: string;
  method?: string;
}

interface LocationOption {
  id: string;
  name: string;
}

const CATEGORIES = ["PROFILE", "COVER", "EXTERIOR", "INTERIOR", "PRODUCT", "AT_WORK", "FOOD_AND_DRINK", "TEAM"];

const BACKEND_STATUS: Record<string, MediaStatus> = {
  draft: "DRAFT",
  scheduled: "SCHEDULED",
  published: "PUBLISHED",
  failed: "FAILED",
};

const AUTOPILOT_KEY = "sayvors.media-autopilot";

function normalizeMedia(raw: unknown): MediaItem[] {
  const list = Array.isArray(raw) ? raw : (raw as { media?: unknown[] }).media;
  if (!Array.isArray(list)) return [];
  return (list as Record<string, unknown>[]).map((m: Record<string, unknown>, i: number) => {
    const url = typeof m.image_url === "string" ? m.image_url : undefined;
    return {
      id: String(m.id ?? `m_${i}`),
      type: m.type === "VIDEO" ? "VIDEO" : "PHOTO",
      source: "OWN" as const,
      category: String(m.category ?? "EXTERIOR"),
      thumbnailUrl: url,
      sourceUrl: url,
      views: 0,
      createdAt: String(m.created_at ?? m.createdAt ?? new Date().toISOString().slice(0, 10)).slice(0, 10),
      isProfile: m.is_profile === true,
      isCover: m.is_cover === true,
      status: (typeof m.status === "string" ? BACKEND_STATUS[m.status] : undefined) ?? "DRAFT",
      scheduledAt: m.scheduled_on ? String(m.scheduled_on) : undefined,
      error: typeof m.error === "string" ? m.error : undefined,
      method: typeof m.publish_method === "string" ? m.publish_method : undefined,
    };
  });
}

export default function MediaPage() {
  return (
    <Suspense>
      <MediaInner />
    </Suspense>
  );
}

function MediaInner() {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [items, setItems] = useState<MediaItem[]>([]);
  const [tab, setTab] = useState<MediaTab>("all");
  const [showUpload, setShowUpload] = useState(false);
  const [viewing, setViewing] = useState<MediaItem | null>(null);
  const [editingCategory, setEditingCategory] = useState("");
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Upload form state
  const [uploadMode, setUploadMode] = useState<"file" | "url">("file");
  const [uploadType, setUploadType] = useState<MediaType>("PHOTO");
  const [uploadCategory, setUploadCategory] = useState("EXTERIOR");
  const [uploadUrl, setUploadUrl] = useState("");
  const [uploadDescription, setUploadDescription] = useState("");
  // How the photo reaches Google. Only "post" is wired (Localith publishes
  // posts carrying image URLs; it offers no gallery upload or profile/cover
  // assignment). Gallery/profile are honest disabled options until the
  // native Google connection lands.
  const [publishMethod, setPublishMethod] = useState<"post" | "gallery" | "profile">("post");
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduledAt, setScheduledAt] = useState("");
  const [uploading, setUploading] = useState(false);
  const [publishingId, setPublishingId] = useState<string | null>(null);
  const [hideAutopilot, setHideAutopilot] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(AUTOPILOT_KEY) === "1") setHideAutopilot(true);
    } catch {
      /* storage unavailable */
    }
  }, []);

  const dismissAutopilot = () => {
    setHideAutopilot(true);
    try {
      localStorage.setItem(AUTOPILOT_KEY, "1");
    } catch {
      /* storage unavailable */
    }
  };

  const openScheduleUpload = () => {
    setUploadType("PHOTO");
    setUploadMode("url");
    setScheduleEnabled(true);
    setShowUpload(true);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Real branches: every Localith-connected listing (same as Posts).
        try {
          const conns = (await apiFetch("/api/v1/integrations/localith/connections")) as { listing_id: string; listing_name: string }[];
          if (!cancelled && Array.isArray(conns) && conns.length > 0) {
            const locs = conns.map((c) => ({ id: c.listing_id, name: c.listing_name }));
            if (!cancelled) {
              setLocations(locs);
              setSelectedId(locs[0].id);
              return;
            }
          }
        } catch {
          /* fall through to channels */
        }
        const data = await apiFetch("/api/v1/channels/?limit=100");
        const googleChannels = (data.channels ?? [])
          .filter((channel: { platform: string }) => channel.platform === "google_reviews")
          .map((channel: { id: string; display_name: string | null }) => ({
            id: channel.id,
            name: channel.display_name ?? "Google location",
          }));
        if (!cancelled) {
          setLocations(googleChannels);
          if (googleChannels.length) setSelectedId(googleChannels[0].id);
        }
      } catch {
        if (!cancelled) {
          setLocations([]);
          setSelectedId(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const loadItems = async () => {
    const q = selectedId ? `?listing_id=${encodeURIComponent(selectedId)}` : "";
    const data = await apiFetch(`/api/v1/media/${q}`);
    return normalizeMedia(data);
  };

  const refreshItems = async () => {
    try {
      setItems(await loadItems());
    } catch {
      /* keep current list on failure */
    }
  };

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    (async () => {
      try {
        const items = await loadItems();
        if (!cancelled) setItems(items);
      } catch {
        if (!cancelled) setItems([]);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const counts = useMemo(() => ({
    all: items.length,
    photos: items.filter((m) => m.type === "PHOTO" && m.source === "OWN").length,
    videos: items.filter((m) => m.type === "VIDEO" && m.source === "OWN").length,
    customer: items.filter((m) => m.source === "CUSTOMER").length,
    scheduled: items.filter((m) => m.status === "SCHEDULED").length,
  }), [items]);

  const filtered = items.filter((m) => {
    if (tab === "photos") return m.type === "PHOTO" && m.source === "OWN";
    if (tab === "videos") return m.type === "VIDEO" && m.source === "OWN";
    if (tab === "customer") return m.source === "CUSTOMER";
    if (tab === "scheduled") return m.status === "SCHEDULED";
    return true;
  });

  const scheduleValid = !scheduleEnabled || !!scheduledAt;

  const handleUpload = async () => {
    if (!selectedId) {
      setBanner({ kind: "err", text: "Connect a location first." });
      return;
    }
    if (uploadMode === "url" && !uploadUrl.trim()) return;
    if (uploadType === "VIDEO" && scheduleEnabled) {
      setBanner({ kind: "err", text: "Video auto-publishing isn't supported by the provider yet — save videos to the library for now." });
      return;
    }
    if (scheduleEnabled && !scheduledAt) {
      setBanner({ kind: "err", text: "Pick a date and time to schedule this photo." });
      return;
    }
    setUploading(true);
    try {
      await apiFetch("/api/v1/media/", {
        method: "POST",
        body: JSON.stringify({
          listing_id: selectedId,
          image_url: uploadMode === "url" ? uploadUrl.trim() : "",
          type: uploadType,
          category: uploadCategory,
          caption: uploadDescription.trim(),
          action: scheduleEnabled ? "schedule" : "publish",
          scheduled_on: scheduleEnabled && scheduledAt ? new Date(scheduledAt).toISOString() : null,
          publish_method: publishMethod,
        }),
      });
      await refreshItems();
      setShowUpload(false);
      setUploadUrl("");
      setUploadDescription("");
      setScheduleEnabled(false);
      setScheduledAt("");
      setBanner({
        kind: "ok",
        text: scheduleEnabled
          ? "Photo scheduled — it goes live on Google inside a post at that time."
          : "Photo published to Google.",
      });
      setTimeout(() => setBanner(null), 4000);
    } catch (e) {
      setBanner({ kind: "err", text: e instanceof Error ? e.message.slice(0, 200) : "Upload failed." });
    }
    setUploading(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await apiFetch(`/api/v1/media/${id}`, { method: "DELETE" });
    } catch { /* optimistic */ }
    setItems((prev) => prev.filter((m) => m.id !== id));
    setViewing(null);
  };

  const handlePublishNow = async (id: string) => {
    setPublishingId(id);
    try {
      await apiFetch(`/api/v1/media/${id}/publish`, { method: "POST" });
      await refreshItems();
      setViewing((prev) => (prev && prev.id === id ? { ...prev, status: "PUBLISHED" as const, error: undefined } : prev));
      setBanner({ kind: "ok", text: "Photo published to Google." });
      setTimeout(() => setBanner(null), 4000);
    } catch (e) {
      setBanner({ kind: "err", text: e instanceof Error ? e.message.slice(0, 200) : "Publish failed." });
      await refreshItems();
    } finally {
      setPublishingId(null);
    }
  };

  const handleCategorySave = async () => {
    if (!viewing) return;
    try {
      await apiFetch(`/api/v1/media/${viewing.id}`, {
        method: "PUT",
        body: JSON.stringify({ category: editingCategory }),
      });
    } catch { /* optimistic */ }
    setItems((prev) => prev.map((m) => m.id === viewing.id ? { ...m, category: editingCategory } : m));
    setViewing({ ...viewing, category: editingCategory });
  };

  const handleSetFlag = async (flag: "isProfile" | "isCover") => {
    if (!viewing) return;
    const patch = flag === "isProfile" ? { isProfile: true } : { isCover: true };
    try {
      await apiFetch(`/api/v1/media/${viewing.id}`, {
        method: "PUT",
        body: JSON.stringify(patch),
      });
    } catch { /* optimistic */ }
    setItems((prev) => prev.map((m) => m.id === viewing.id ? { ...m, ...patch } : m));
    setViewing({ ...viewing, ...patch });
  };

  const openView = (m: MediaItem) => {
    setViewing(m);
    setEditingCategory(m.category);
  };

  if (loading) return <div className="flex h-full items-center justify-center"><LogoLoader size={32} /></div>;

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-ink/[0.06] bg-white/80 px-6 py-4 backdrop-blur dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-[18px] font-bold text-ink dark:text-fog">Media</h1>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">{items.length} items · {items.reduce((a, m) => a + m.views, 0).toLocaleString()} total views</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value)}
                className="w-52 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog">
                {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            <button onClick={() => setShowUpload(true)} className="rounded-xl bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:opacity-90">
              + Upload Media
            </button>
          </div>
        </div>
        {banner && (
          <div className={`mt-3 rounded-lg px-3 py-1.5 text-[12px] font-medium ${banner.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{banner.text}</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-4xl space-y-4">
          {!hideAutopilot && (
            <div className="rounded-2xl border border-deep-violet/15 bg-gradient-to-br from-deep-violet/[0.06] to-transparent p-4 dark:border-deep-violet/25">
              <div className="flex items-start justify-between gap-3">
                <h3 className="text-[14px] font-bold text-ink dark:text-fog">📸 Let your photos sell while you work</h3>
                <button onClick={dismissAutopilot} aria-label="Dismiss" className="shrink-0 rounded-md px-1.5 py-0.5 text-[13px] text-ink/30 hover:bg-ink/[0.05] hover:text-ink/60">✕</button>
              </div>
              <p className="mt-0.5 text-[12px] text-ink/50 dark:text-fog/50">Pick a photo and a time — it appears on your Google listing by itself. Nothing to remember.</p>
              <ul className="mt-2.5 space-y-1.5">
                {[
                  ["New photos bring more customers", "Listings with 10+ recent photos get about double the views. One new photo a week beats uploading 50 once a year."],
                  ["Set it once, forget it", "Schedule Sunday 9am and a fresh photo shows on your Google page every week while you run the shop."],
                  ["Sale photos on time, every time", "Offer and event shots go up with the promotion — not a month later when nobody cares."],
                ].map(([title, body]) => (
                  <li key={title} className="flex gap-2 text-[12px] leading-relaxed">
                    <span aria-hidden className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet" />
                    <span className="text-ink/70 dark:text-fog/70"><strong className="font-semibold text-ink dark:text-fog">{title} — </strong>{body}</span>
                  </li>
                ))}
              </ul>
              <button onClick={openScheduleUpload} className="mt-3 rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:opacity-90">
                Schedule a photo
              </button>
            </div>
          )}
          <div className="flex gap-1 overflow-x-auto rounded-xl bg-ink/[0.03] p-1 dark:bg-fog/[0.04]">
            {([
              { key: "all", label: `All Media (${counts.all})` },
              { key: "photos", label: `Photos (${counts.photos})` },
              { key: "videos", label: `Videos (${counts.videos})` },
              { key: "scheduled", label: `Scheduled (${counts.scheduled})` },
              { key: "customer", label: `Customer Photos (${counts.customer})` },
            ] as const).map((t) => (
              <button key={t.key} onClick={() => setTab(t.key)}
                className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-semibold transition ${tab === t.key ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-fog" : "text-ink/45 hover:text-ink/70 dark:text-fog/45"}`}>
                {t.label}
              </button>
            ))}
          </div>

          {filtered.length === 0 ? (
            <div className="flex flex-col items-center rounded-2xl border border-dashed border-ink/[0.12] bg-white py-16 dark:border-fog/[0.12] dark:bg-ink">
              <p className="text-[14px] font-medium text-ink/40 dark:text-fog/40">No media here yet</p>
              <p className="mt-1 text-[12px] text-ink/30 dark:text-fog/30">Upload photos or videos for this location.</p>
              <button onClick={() => setShowUpload(true)} className="mt-4 rounded-xl bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white">+ Upload Media</button>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {filtered.map((m) => (
                <button key={m.id} onClick={() => openView(m)} className="group overflow-hidden rounded-2xl border border-ink/[0.06] bg-white text-left transition hover:shadow-md dark:border-fog/[0.06] dark:bg-ink">
                  <div className={`relative flex aspect-[4/3] items-center justify-center ${m.type === "VIDEO" ? "bg-gradient-to-br from-ink to-deep-violet" : "bg-gradient-to-br from-violet-soft/40 to-sky/20"}`}>
                    {m.type === "VIDEO" ? (
                      <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/20 backdrop-blur">
                        <svg viewBox="0 0 24 24" fill="white" className="h-5 w-5"><path d="M8 5v14l11-7z" /></svg>
                      </span>
                    ) : (
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-8 w-8 text-ink/20 dark:text-fog/20"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></svg>
                    )}
                    {m.isProfile && <span className="absolute left-2 top-2 rounded-full bg-deep-violet px-2 py-0.5 text-[9px] font-bold text-white">PROFILE</span>}
                    {m.isCover && <span className="absolute left-2 top-2 rounded-full bg-emerald-500 px-2 py-0.5 text-[9px] font-bold text-white">COVER</span>}
                    {m.source === "CUSTOMER" && <span className="absolute right-2 top-2 rounded-full bg-black/50 px-2 py-0.5 text-[9px] font-bold text-white backdrop-blur">CUSTOMER</span>}
                  </div>
                  <div className="p-2.5">
                    <p className="truncate text-[12px] font-semibold text-ink dark:text-fog">{m.category.replace(/_/g, " ")}</p>
                    <p className="flex flex-wrap items-center gap-1.5 text-[10px] text-ink/35 dark:text-fog/35">
                      <span>{m.views.toLocaleString()} views</span>
                      {m.attribution ? <span> · {m.attribution}</span> : null}
                      {m.status === "SCHEDULED" && m.scheduledAt && (
                        <span className="rounded-full bg-amber-100 px-1.5 py-px font-semibold text-amber-700">🕑 {new Date(m.scheduledAt).toLocaleString()}</span>
                      )}
                      {m.status === "FAILED" && (
                        <span className="rounded-full bg-red-100 px-1.5 py-px font-semibold text-red-700">Failed</span>
                      )}
                    </p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {showUpload && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowUpload(false)}>
          <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl dark:bg-ink" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-ink/[0.06] px-5 py-4 dark:border-fog/[0.06]">
              <h2 className="text-[15px] font-bold text-ink dark:text-fog">Upload Media</h2>
              <button onClick={() => setShowUpload(false)} className="text-ink/30 hover:text-ink/60"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg></button>
            </div>
            <div className="flex border-b border-ink/[0.06] dark:border-fog/[0.06]">
              <button onClick={() => setUploadMode("file")} className={`flex-1 py-2.5 text-[13px] font-semibold ${uploadMode === "file" ? "border-b-2 border-deep-violet text-deep-violet" : "text-ink/40"}`}>File upload</button>
              <button onClick={() => setUploadMode("url")} className={`flex-1 py-2.5 text-[13px] font-semibold ${uploadMode === "url" ? "border-b-2 border-deep-violet text-deep-violet" : "text-ink/40"}`}>Add from URL</button>
            </div>
            <div className="space-y-4 p-5">
              <div>
                <label className="mb-1 block text-[12px] font-medium text-ink/50">Publish to Google as</label>
                <div className="space-y-1.5">
                  {([
                    { key: "post", title: "Google post", note: "Photo goes live inside a post — works today.", wired: true },
                    { key: "gallery", title: "Photo gallery", note: "Straight into the gallery — needs the native Google connection.", wired: false },
                    { key: "profile", title: "Profile / cover photo", note: "Set as profile or cover — needs the native Google connection.", wired: false },
                  ] as const).map((m) => (
                    <button
                      key={m.key}
                      type="button"
                      disabled={!m.wired}
                      onClick={() => setPublishMethod(m.key)}
                      aria-pressed={publishMethod === m.key}
                      title={m.wired ? undefined : "Available with the native Google connection"}
                      className={`flex w-full items-center gap-2.5 rounded-xl border p-3 text-left transition ${!m.wired ? "cursor-not-allowed border-ink/[0.06] bg-ink/[0.02] opacity-60 dark:border-fog/[0.06]" : publishMethod === m.key ? "border-deep-violet bg-deep-violet/[0.06]" : "border-ink/[0.08] hover:border-deep-violet/30"}`}
                    >
                      <span aria-hidden className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 ${publishMethod === m.key && m.wired ? "border-deep-violet" : "border-ink/20"}`}>
                        {publishMethod === m.key && m.wired && <span className="h-2 w-2 rounded-full bg-deep-violet" />}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-semibold text-ink dark:text-fog">
                          {m.title}
                          {!m.wired && <span className="ml-1.5 rounded-full bg-ink/[0.06] px-1.5 py-px align-middle text-[9px] font-bold uppercase tracking-wide text-ink/40">Soon</span>}
                        </span>
                        <span className="block text-[11px] text-ink/40">{m.note}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex gap-2">
                {(["PHOTO", "VIDEO"] as const).map((t) => (
                  <button key={t} onClick={() => setUploadType(t)}
                    className={`flex-1 rounded-lg border py-2 text-[12px] font-semibold transition ${uploadType === t ? "border-deep-violet bg-deep-violet/[0.06] text-deep-violet" : "border-ink/[0.08] text-ink/50"}`}>
                    {t === "PHOTO" ? "Photo" : "Video"}
                  </button>
                ))}
              </div>
              {uploadMode === "file" ? (
                <div className="flex flex-col items-center rounded-xl border-2 border-dashed border-ink/[0.12] py-8">
                  <p className="text-[12px] text-ink/40">Direct file hosting isn&apos;t connected yet</p>
                  <p className="mt-1 max-w-[26ch] text-center text-[11px] text-ink/30">Paste a hosted image URL instead — it goes live on Google the same way.</p>
                  <button onClick={() => setUploadMode("url")} className="mt-3 rounded-lg bg-deep-violet/[0.08] px-3 py-1.5 text-[12px] font-semibold text-deep-violet hover:bg-deep-violet/[0.15]">
                    Use URL instead
                  </button>
                </div>
              ) : (
                <div>
                  <label className="mb-1 block text-[12px] font-medium text-ink/50">Media URL</label>
                  <input value={uploadUrl} onChange={(e) => setUploadUrl(e.target.value)} placeholder="https://..." className="input-field" />
                </div>
              )}
              <div>
                <label className="mb-1 block text-[12px] font-medium text-ink/50">Category</label>
                <select value={uploadCategory} onChange={(e) => setUploadCategory(e.target.value)} className="input-field">
                  {CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[12px] font-medium text-ink/50">Description (goes live as the post caption)</label>
                <textarea value={uploadDescription} onChange={(e) => setUploadDescription(e.target.value)} rows={2} maxLength={200} placeholder="Optional caption..." className="input-field resize-y" />
              </div>
              <label className="flex cursor-pointer items-center justify-between rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <span>
                  <span className="block text-[13px] font-semibold text-ink dark:text-fog">Schedule for later</span>
                  <span className="block text-[11px] text-ink/40">Photo goes live on Google inside a post at that time.</span>
                </span>
                <span onClick={() => setScheduleEnabled(!scheduleEnabled)}
                  className={`h-5 w-9 shrink-0 rounded-full transition ${scheduleEnabled ? "bg-deep-violet" : "bg-ink/15 dark:bg-fog/15"}`}>
                  <span className={`block h-4 w-4 rounded-full bg-white shadow transition-transform ${scheduleEnabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
                </span>
              </label>
              {scheduleEnabled && (
                <input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} className="input-field" />
              )}
              {uploadType === "VIDEO" && (
                <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-700">Videos save to your library — auto-publishing works for photos (the provider takes image URLs, not video).</p>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-ink/[0.06] px-5 py-3 dark:border-fog/[0.06]">
              <button onClick={() => setShowUpload(false)} className="btn-secondary">Cancel</button>
              <button onClick={handleUpload} disabled={uploading || uploadMode === "file" || (uploadMode === "url" && !uploadUrl.trim()) || !scheduleValid} className="btn-primary disabled:opacity-50" title={uploadMode === "file" ? "File hosting isn't connected yet — use Add from URL" : !scheduleValid ? "Pick a date and time to schedule" : undefined}>
                {uploading ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : scheduleEnabled ? "Schedule photo" : "Publish photo"}
              </button>
            </div>
          </div>
        </div>
      )}

      {viewing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setViewing(null)}>
          <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl dark:bg-ink" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-ink/[0.06] px-5 py-4 dark:border-fog/[0.06]">
              <h2 className="text-[15px] font-bold text-ink dark:text-fog">Media details</h2>
              <button onClick={() => setViewing(null)} className="text-ink/30 hover:text-ink/60"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg></button>
            </div>
            <div className="space-y-3 p-5">
              <div className="grid grid-cols-2 gap-3 text-[12px]">
                <div><p className="text-ink/40">Type</p><p className="font-semibold text-ink dark:text-fog">{viewing.type}</p></div>
                <div><p className="text-ink/40">Views</p><p className="font-semibold text-ink dark:text-fog">{viewing.views.toLocaleString()}</p></div>
                <div><p className="text-ink/40">Source</p><p className="font-semibold text-ink dark:text-fog">{viewing.source === "CUSTOMER" ? "Customer" : "Business"}</p></div>
                <div><p className="text-ink/40">Uploaded</p><p className="font-semibold text-ink dark:text-fog">{viewing.createdAt}</p></div>
                <div><p className="text-ink/40">Goes live as</p><p className="font-semibold text-ink dark:text-fog">{viewing.method === "gallery" ? "Photo gallery" : viewing.method === "profile" ? "Profile / cover" : "Google post"}</p></div>
              </div>
              {viewing.attribution && (
                <p className="rounded-lg bg-ink/[0.03] px-3 py-2 text-[12px] text-ink/50 dark:bg-fog/[0.04] dark:text-fog/50">By {viewing.attribution}</p>
              )}
              {viewing.source === "OWN" && (viewing.status === "SCHEDULED" || viewing.status === "FAILED") && (
                <div className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.08]">
                  <p className="text-[12px] font-medium text-ink/70 dark:text-fog/70">
                    {viewing.status === "SCHEDULED"
                      ? viewing.scheduledAt
                        ? `Scheduled — goes live ${new Date(viewing.scheduledAt).toLocaleString()}`
                        : "Scheduled"
                      : "Publishing failed — retries automatically, or publish now."}
                  </p>
                  {viewing.status === "FAILED" && viewing.error && (
                    <p className="mt-1 text-[11px] text-red-600">{viewing.error}</p>
                  )}
                  <button
                    onClick={() => handlePublishNow(viewing.id)}
                    disabled={publishingId !== null}
                    className="mt-2 w-full rounded-xl bg-emerald-500 py-2 text-[12px] font-semibold text-white transition hover:bg-emerald-600 disabled:opacity-50"
                  >
                    {publishingId === viewing.id ? "Publishing…" : "Publish now"}
                  </button>
                </div>
              )}
              {viewing.source === "OWN" ? (
                <>
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-ink/50">Category</label>
                    <div className="flex gap-2">
                      <select value={editingCategory} onChange={(e) => setEditingCategory(e.target.value)} className="input-field flex-1">
                        {CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
                      </select>
                      <button onClick={handleCategorySave} className="btn-secondary">Save</button>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => handleSetFlag("isProfile")} className="btn-secondary flex-1">Set as profile</button>
                    <button onClick={() => handleSetFlag("isCover")} className="btn-secondary flex-1">Set as cover</button>
                  </div>
                  <p className="text-[10px] text-ink/30">File and description cannot be changed after upload (Google API limit).</p>
                  <button onClick={() => handleDelete(viewing.id)} className="w-full rounded-xl border border-red-200 py-2 text-[12px] font-semibold text-red-600 hover:bg-red-50">Delete this media</button>
                </>
              ) : (
                <p className="rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-700">Customer photos are read-only. You cannot edit or delete them.</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
