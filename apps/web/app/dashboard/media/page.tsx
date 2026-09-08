"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type MediaType = "PHOTO" | "VIDEO";
type MediaSource = "OWN" | "CUSTOMER";
type MediaTab = "all" | "photos" | "videos" | "customer";

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
}

interface LocationOption {
  id: string;
  name: string;
}

const MOCK_LOCATIONS: LocationOption[] = [
  { id: "loc_1", name: "Sayvors Al Malqa" },
];

const MOCK_MEDIA: MediaItem[] = [
  { id: "m1", type: "PHOTO", source: "OWN", category: "EXTERIOR", views: 1240, createdAt: "2026-08-20", isCover: true },
  { id: "m2", type: "PHOTO", source: "OWN", category: "INTERIOR", views: 860, createdAt: "2026-08-22" },
  { id: "m3", type: "VIDEO", source: "OWN", category: "AT_WORK", views: 2130, createdAt: "2026-08-25", isProfile: true },
  { id: "m4", type: "PHOTO", source: "CUSTOMER", category: "FOOD_AND_DRINK", views: 540, attribution: "Ahmed K.", createdAt: "2026-08-28" },
  { id: "m5", type: "PHOTO", source: "CUSTOMER", category: "INTERIOR", views: 310, attribution: "Sara M.", createdAt: "2026-09-01" },
];

const CATEGORIES = ["PROFILE", "COVER", "EXTERIOR", "INTERIOR", "PRODUCT", "AT_WORK", "FOOD_AND_DRINK", "TEAM"];

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
  const [uploading, setUploading] = useState(false);

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
        const data = await apiFetch(`/api/v1/locations/${selectedId}/media`);
        if (!cancelled) setItems(data.media ?? MOCK_MEDIA);
      } catch {
        if (!cancelled) setItems(MOCK_MEDIA);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  const counts = useMemo(() => ({
    all: items.length,
    photos: items.filter((m) => m.type === "PHOTO" && m.source === "OWN").length,
    videos: items.filter((m) => m.type === "VIDEO" && m.source === "OWN").length,
    customer: items.filter((m) => m.source === "CUSTOMER").length,
  }), [items]);

  const filtered = items.filter((m) => {
    if (tab === "photos") return m.type === "PHOTO" && m.source === "OWN";
    if (tab === "videos") return m.type === "VIDEO" && m.source === "OWN";
    if (tab === "customer") return m.source === "CUSTOMER";
    return true;
  });

  const handleUpload = async () => {
    if (uploadMode === "url" && !uploadUrl.trim()) return;
    setUploading(true);
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/media`, {
        method: "POST",
        body: JSON.stringify({
          type: uploadType,
          category: uploadCategory,
          sourceUrl: uploadMode === "url" ? uploadUrl.trim() : undefined,
          description: uploadDescription.trim() || undefined,
        }),
      });
      const item: MediaItem = {
        id: `m_${Date.now()}`,
        type: uploadType,
        source: "OWN",
        category: uploadCategory,
        views: 0,
        createdAt: new Date().toISOString().slice(0, 10),
      };
      setItems((prev) => [item, ...prev]);
      setShowUpload(false);
      setUploadUrl("");
      setUploadDescription("");
      setBanner({ kind: "ok", text: "Media uploaded." });
      setTimeout(() => setBanner(null), 2500);
    } catch {
      setBanner({ kind: "err", text: "Upload failed." });
    }
    setUploading(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/media/${id}`, { method: "DELETE" });
    } catch { /* optimistic */ }
    setItems((prev) => prev.filter((m) => m.id !== id));
    setViewing(null);
  };

  const handleCategorySave = async () => {
    if (!viewing) return;
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/media/${viewing.id}`, {
        method: "PATCH",
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
      await apiFetch(`/api/v1/locations/${selectedId}/media/${viewing.id}`, {
        method: "PATCH",
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
          <div className="flex gap-1 overflow-x-auto rounded-xl bg-ink/[0.03] p-1 dark:bg-fog/[0.04]">
            {([
              { key: "all", label: `All Media (${counts.all})` },
              { key: "photos", label: `Photos (${counts.photos})` },
              { key: "videos", label: `Videos (${counts.videos})` },
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
                    <p className="text-[10px] text-ink/35 dark:text-fog/35">{m.views.toLocaleString()} views{m.attribution ? ` · ${m.attribution}` : ""}</p>
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
                  <p className="text-[12px] text-ink/40">Drop {uploadType === "PHOTO" ? "photo" : "video"} or click to browse</p>
                  <p className="text-[10px] text-ink/25">JPG, PNG{uploadType === "VIDEO" ? ", MP4" : ""} up to 25MB</p>
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
                <label className="mb-1 block text-[12px] font-medium text-ink/50">Description (set once at upload)</label>
                <textarea value={uploadDescription} onChange={(e) => setUploadDescription(e.target.value)} rows={2} maxLength={200} placeholder="Optional caption..." className="input-field resize-y" />
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t border-ink/[0.06] px-5 py-3 dark:border-fog/[0.06]">
              <button onClick={() => setShowUpload(false)} className="btn-secondary">Cancel</button>
              <button onClick={handleUpload} disabled={uploading || (uploadMode === "url" && !uploadUrl.trim())} className="btn-primary disabled:opacity-50">
                {uploading ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Uploading...</span> : "Upload"}
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
              </div>
              {viewing.attribution && (
                <p className="rounded-lg bg-ink/[0.03] px-3 py-2 text-[12px] text-ink/50 dark:bg-fog/[0.04] dark:text-fog/50">By {viewing.attribution}</p>
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
