"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import Modal from "./Modal";
import MediaUploadDialog from "./MediaUploadDialog";
import MediaDetailsDialog from "./MediaDetailsDialog";
import { mediaStatusLabel, goesLiveWithinMinuteText } from "@/lib/schedule-copy";
import type { MediaItem } from "../MediaPage";

interface LocationOption {
  id: string;
  name: string;
  channelId: string;
}

type StatusFilter = "all" | "draft" | "scheduled" | "published" | "failed";
type SortKey = "newest" | "oldest" | "scheduled";

interface Notice {
  kind: "ok" | "err";
  text: string;
  details?: string;
}

const STATUS_TONE: Record<string, string> = {
  DRAFT: "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
  SCHEDULED: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  PUBLISHED: "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  FAILED: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
};

export default function MediaLibrary({ initialLocationId, onOpenGoogle }: { initialLocationId?: string | null; onOpenGoogle?: () => void }) {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [items, setItems] = useState<MediaItem[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortKey>("newest");
  const [selectionMode, setSelectionMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [viewing, setViewing] = useState<MediaItem | null>(null);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  const selectedLocation = useMemo(() => locations.find((l) => l.id === selectedId) ?? null, [locations, selectedId]);

  // Load locations
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/channels?limit=100");
        const google = (data.channels ?? [])
          .filter((c: { platform: string }) => c.platform === "google_reviews")
          .map((c: { id: string; display_name: string | null; listing_id?: string | null }) => ({
            id: c.listing_id ?? c.id,
            name: c.display_name ?? "Google location",
            channelId: c.id,
          }));
        if (cancelled) return;
        setLocations(google);
        const preferred = initialLocationId && google.some((l: LocationOption) => l.id === initialLocationId)
          ? initialLocationId
          : google[0]?.id ?? null;
        setSelectedId(preferred);
      } catch {
        if (!cancelled) setLocations([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [initialLocationId]);

  const loadItems = async () => {
    if (!selectedId) return [];
    const data = await apiFetch(`/api/v1/media/?listing_id=${encodeURIComponent(selectedId)}`);
    return (Array.isArray(data) ? data : data?.media ?? []).map((m: unknown) => normalizeMediaItem(m));
  };

  // Re-implement normalize locally to avoid circular import of MediaPage's normalize
  const refreshItems = async () => {
    if (!selectedId) { setItems([]); return; }
    try {
      const data = await apiFetch(`/api/v1/media/?listing_id=${encodeURIComponent(selectedId)}`);
      const list = Array.isArray(data) ? data : (data?.media ?? []);
      setItems(list.map((m: unknown, i: number) => normalizeMediaItem(m, i)));
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message.slice(0, 200) : "Could not load media.");
    }
  };

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const data = await apiFetch(`/api/v1/media/?listing_id=${encodeURIComponent(selectedId)}`);
        const list = Array.isArray(data) ? data : (data?.media ?? []);
        if (!cancelled) {
          setItems(list.map((m: unknown, i: number) => normalizeMediaItem(m, i)));
          setLoadError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setItems([]);
          setLoadError(e instanceof Error ? e.message.slice(0, 200) : "Could not load media.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  const filtered = useMemo(() => {
    let list = items;
    if (statusFilter !== "all") {
      list = list.filter((m) => m.status?.toLowerCase() === statusFilter);
    }
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter((m) =>
        m.category.toLowerCase().includes(q) ||
        (m.attribution ?? "").toLowerCase().includes(q) ||
        (m.method ?? "").toLowerCase().includes(q)
      );
    }
    const sorted = [...list];
    if (sort === "newest") sorted.sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
    else if (sort === "oldest") sorted.sort((a, b) => (a.createdAt > b.createdAt ? 1 : -1));
    else if (sort === "scheduled") sorted.sort((a, b) => (a.scheduledAt ?? "9999").localeCompare(b.scheduledAt ?? "9999"));
    return sorted;
  }, [items, statusFilter, search, sort]);

  const counts = useMemo(() => ({
    all: items.length,
    draft: items.filter((m) => m.status === "DRAFT").length,
    scheduled: items.filter((m) => m.status === "SCHEDULED").length,
    published: items.filter((m) => m.status === "PUBLISHED").length,
    failed: items.filter((m) => m.status === "FAILED").length,
  }), [items]);

  // selection helpers
  useEffect(() => {
    if (selectAllRef.current) {
      const n = selected.size;
      selectAllRef.current.indeterminate = n > 0 && n < filtered.length;
      selectAllRef.current.checked = filtered.length > 0 && n === filtered.length;
    }
  }, [selected, filtered.length]);

  const toggleSelect = (id: string, index: number, shift: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (shift && lastSelectedIndex !== null) {
        const [a, b] = [Math.min(lastSelectedIndex, index), Math.max(lastSelectedIndex, index)];
        for (let i = a; i <= b; i++) {
          next.add(filtered[i].id);
        }
      } else {
        if (next.has(id)) next.delete(id); else next.add(id);
      }
      return next;
    });
    setLastSelectedIndex(index);
  };

  const selectAll = () => setSelected(new Set(filtered.map((m) => m.id)));
  const clearSelection = () => { setSelected(new Set()); setSelectionMode(false); };

  const eligiblePublish = useMemo(() => filtered.filter((m) => selected.has(m.id) && m.type === "PHOTO" && (m.status === "DRAFT" || m.status === "SCHEDULED" || m.status === "FAILED")), [filtered, selected]);
  const selectedItems = useMemo(() => filtered.filter((m) => selected.has(m.id)), [filtered, selected]);

  const bulkPublish = async () => {
    if (eligiblePublish.length === 0) {
      setNotice({ kind: "err", text: "None of the selected items can be published right now (only draft, scheduled or failed photos)." });
      return;
    }
    setBulkBusy(true);
    let ok = 0, fail = 0;
    const errs: string[] = [];
    for (const m of eligiblePublish) {
      try {
        await apiFetch(`/api/v1/media/${m.id}/publish`, { method: "POST" });
        ok++;
      } catch (e) {
        fail++;
        errs.push(e instanceof Error ? e.message.slice(0, 120) : "Failed");
      }
    }
    await refreshItems();
    setBulkBusy(false);
    setNotice({
      kind: fail === 0 ? "ok" : "err",
      text: fail === 0 ? `Published ${ok} photo${ok === 1 ? "" : "s"} to Google.` : `${ok} published, ${fail} failed.`,
      details: errs.length ? errs.slice(0, 3).join(" · ") : undefined,
    });
    setSelected(new Set());
    setSelectionMode(false);
  };

  const bulkDelete = async () => {
    setBulkBusy(true);
    let ok = 0, fail = 0;
    for (const m of selectedItems) {
      try {
        await apiFetch(`/api/v1/media/${m.id}`, { method: "DELETE" });
        ok++;
      } catch {
        fail++;
      }
    }
    await refreshItems();
    setBulkBusy(false);
    setConfirmBulkDelete(false);
    setNotice({
      kind: fail === 0 ? "ok" : "err",
      text: fail === 0 ? `Removed ${ok} item${ok === 1 ? "" : "s"} from your library.` : `${ok} removed, ${fail} failed.`,
    });
    setSelected(new Set());
    setSelectionMode(false);
  };

  const handleDeleteOne = async (id: string) => {
    try {
      await apiFetch(`/api/v1/media/${id}`, { method: "DELETE" });
    } catch { /* optimistic */ }
    setItems((prev) => prev.filter((m) => m.id !== id));
    setViewing(null);
  };

  const handlePublishOne = async (id: string) => {
    try {
      await apiFetch(`/api/v1/media/${id}/publish`, { method: "POST" });
      await refreshItems();
      setNotice({ kind: "ok", text: "Photo published to Google." });
    } catch (e) {
      setNotice({ kind: "err", text: e instanceof Error ? e.message.slice(0, 200) : "Publish failed." });
      await refreshItems();
    }
  };

  const handleUpdateOne = async (id: string, patch: Record<string, unknown>) => {
    try {
      await apiFetch(`/api/v1/media/${id}`, { method: "PUT", body: JSON.stringify(patch) });
      await refreshItems();
      setNotice({ kind: "ok", text: "Changes saved." });
    } catch (e) {
      const msg = e instanceof Error ? e.message.slice(0, 200) : "Save failed.";
      setNotice({ kind: "err", text: msg });
      throw new Error(msg);
    }
  };

  useEffect(() => {
    if (!notice) return;
    if (notice.kind === "ok") {
      const t = setTimeout(() => setNotice(null), 4000);
      return () => clearTimeout(t);
    }
  }, [notice]);

  if (loading && locations.length === 0) {
    return <div className="flex h-64 items-center justify-center"><LogoLoader size={28} /></div>;
  }

  if (locations.length === 0) {
    return (
      <div className="mx-auto max-w-3xl rounded-[32px] border border-dashed border-ink/15 bg-white p-10 text-center shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)]">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-deep-violet/10 text-[24px]">📍</div>
        <h3 className="mt-4 text-[17px] font-bold text-ink">No Google locations connected</h3>
        <p className="mt-1 text-[13px] text-ink/55">Connect a Google Business Profile location to upload and publish media.</p>
        <a href="/dashboard/channels" className="mt-5 inline-flex rounded-[20px] bg-deep-violet px-5 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90">Connect Google</a>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[20px] font-bold text-ink dark:text-fog">Media library</h2>
          <p className="mt-0.5 text-[13px] text-ink/55 dark:text-fog/55">
            {items.length} item{items.length === 1 ? "" : "s"} · {counts.published} live on Google
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <select
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value)}
              className="w-60 appearance-none rounded-[20px] border border-ink/10 bg-white py-2.5 pl-4 pr-9 text-[13px] font-semibold text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
            >
              {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
            <svg className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </div>
          <button
            type="button"
            onClick={() => setUploadOpen(true)}
            className="rounded-[20px] bg-deep-violet px-5 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90 active:translate-y-0.5 active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40"
          >
            + Upload
          </button>
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
              onClick={clearSelection}
              className="rounded-[20px] border border-ink/10 bg-white px-4 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:bg-white/[0.04] dark:text-fog"
            >
              Cancel
            </button>
          )}
        </div>
      </div>

      {notice && (
        <div className={`flex items-start justify-between gap-3 rounded-[20px] px-4 py-3 text-[13px] font-medium ${notice.kind === "ok" ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300" : "bg-red-50 text-red-700 dark:bg-red-500/10 dark:text-red-300"}`}>
          <div className="min-w-0">
            <p>{notice.text}</p>
            {notice.details && <p className="mt-0.5 text-[11.5px] opacity-80">{notice.details}</p>}
          </div>
          <button type="button" onClick={() => setNotice(null)} className="shrink-0 text-[16px] leading-none opacity-60 hover:opacity-100" aria-label="Dismiss">×</button>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search category or caption…"
          className="min-w-[14rem] flex-1 rounded-[20px] border border-ink/10 bg-white px-4 py-2.5 text-[13px] text-ink outline-none placeholder:text-ink/35 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
        />
        <div className="flex flex-wrap gap-1.5">
          {(["all", "draft", "scheduled", "published", "failed"] as const).map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={`rounded-full px-3 py-1.5 text-[12px] font-bold transition ${statusFilter === s ? "bg-deep-violet text-white" : "bg-ink/[0.04] text-ink/65 hover:bg-ink/[0.08] dark:bg-white/[0.06] dark:text-fog/70"}`}
            >
              {s === "all" ? "All" : s.charAt(0) + s.slice(1).toLowerCase()} ({counts[s]})
            </button>
          ))}
        </div>
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
          className="rounded-[20px] border border-ink/10 bg-white px-3 py-2.5 text-[12px] font-bold text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
        >
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="scheduled">Scheduled soonest</option>
        </select>
      </div>

      {loadError && (
        <div className="flex items-center justify-between rounded-[20px] border border-red-500/40 bg-red-500/10 px-4 py-3 text-[13px] text-red-700 dark:text-red-300">
          <span>{loadError}</span>
          <button type="button" onClick={refreshItems} className="rounded-[16px] border border-red-500/40 px-3 py-1 text-[12px] font-bold">Retry</button>
        </div>
      )}

      {loading ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="aspect-[4/3] animate-pulse rounded-[24px] bg-ink/[0.06]" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center rounded-[32px] border border-dashed border-ink/15 bg-white p-12 text-center shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)]">
          {items.length === 0 ? (
            <>
              <div className="flex h-14 w-14 items-center justify-center rounded-full bg-deep-violet/10 text-[24px]">🖼</div>
              <h3 className="mt-4 text-[17px] font-bold text-ink">No media yet</h3>
              <p className="mt-1 max-w-sm text-[13px] text-ink/55">Upload your first photo to publish it to Google as a post, gallery image, profile or cover.</p>
              <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
                <button type="button" onClick={() => setUploadOpen(true)} className="rounded-[20px] bg-deep-violet px-5 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90">+ Upload media</button>
                {onOpenGoogle && (
                  <button type="button" onClick={onOpenGoogle} className="rounded-[20px] border border-ink/10 bg-white px-5 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05]">See photos already on Google</button>
                )}
              </div>
            </>
          ) : (
            <>
              <h3 className="text-[17px] font-bold text-ink">No matches</h3>
              <p className="mt-1 text-[13px] text-ink/55">Try a different search or clear the filters.</p>
              <button type="button" onClick={() => { setSearch(""); setStatusFilter("all"); }} className="mt-4 rounded-[20px] border border-ink/10 bg-white px-4 py-2 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05]">Clear filters</button>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {filtered.map((m, idx) => {
            const isSelected = selected.has(m.id);
            const status = (m.status ?? "DRAFT") as string;
            return (
              <div
                key={m.id}
                className={`group relative overflow-hidden rounded-[24px] border bg-white shadow-[0_12px_28px_-20px_rgba(20,16,31,0.35)] transition hover:-translate-y-0.5 hover:shadow-[0_20px_40px_-22px_rgba(20,16,31,0.5)] ${isSelected ? "ring-2 ring-deep-violet" : "ring-1 ring-ink/[0.06]"}`}
              >
                <button
                  type="button"
                  onClick={(e) => {
                    if (selectionMode) {
                      toggleSelect(m.id, idx, e.shiftKey);
                    } else {
                      setViewing(m);
                    }
                  }}
                  className="block w-full text-left"
                  aria-pressed={selectionMode ? isSelected : undefined}
                >
                  <div className="relative aspect-[4/3] overflow-hidden bg-ink/[0.04]">
                    {m.thumbnailUrl || m.sourceUrl ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={m.thumbnailUrl || m.sourceUrl} alt="" className="h-full w-full object-cover" loading="lazy" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-[32px] text-ink/20">🖼</div>
                    )}
                    {m.isProfile && <span className="absolute left-2 top-2 rounded-full bg-deep-violet px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">Profile</span>}
                    {m.isCover && <span className="absolute left-2 top-2 rounded-full bg-emerald-600 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">Cover</span>}
                    {m.type === "VIDEO" && <span className="absolute right-2 bottom-2 rounded-full bg-black/60 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-white">Video</span>}
                    <span className={`absolute ${m.isProfile || m.isCover ? "left-2 top-9" : "left-2 top-2"} rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ${STATUS_TONE[status] ?? "bg-ink/10 text-ink/60"}`}>
                      {mediaStatusLabel(status)}
                    </span>
                  </div>
                  <div className="space-y-1 p-3">
                    <p className="truncate text-[12.5px] font-bold text-ink dark:text-fog">{m.category.replace(/_/g, " ")}</p>
                    <p className="truncate text-[11px] text-ink/50 dark:text-fog/50">
                      {status === "SCHEDULED" && m.scheduledAt
                        ? goesLiveWithinMinuteText(m.scheduledAt)
                        : m.method ? m.method.replace(/_/g, " ") : "Google post"}
                    </p>
                  </div>
                </button>
                {selectionMode && (
                  <label className="absolute right-2 top-2 flex h-7 w-7 cursor-pointer items-center justify-center rounded-full bg-white/95 shadow ring-1 ring-ink/10" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(m.id, idx, false)}
                      className="h-4 w-4 accent-deep-violet"
                      aria-label={`Select ${m.category}`}
                    />
                  </label>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Selection action bar */}
      {selectionMode && selected.size > 0 && (
        <div className="sticky bottom-3 z-10 mx-auto flex max-w-3xl flex-wrap items-center justify-between gap-3 rounded-[24px] border border-ink/10 bg-white px-4 py-3 shadow-[0_24px_48px_-24px_rgba(20,16,31,0.6)]">
          <div className="flex items-center gap-3">
            <input
              ref={selectAllRef}
              type="checkbox"
              onChange={(e) => (e.target.checked ? selectAll() : setSelected(new Set()))}
              className="h-4 w-4 accent-deep-violet"
              aria-label="Select all"
            />
            <span className="text-[13px] font-bold text-ink">{selected.size} selected</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={bulkPublish}
              disabled={bulkBusy || eligiblePublish.length === 0}
              className="rounded-[16px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-[0_8px_16px_-10px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90 disabled:cursor-not-allowed disabled:opacity-50"
              title={eligiblePublish.length === 0 ? "Select draft, scheduled or failed photos to publish" : `Publish ${eligiblePublish.length} photo(s)`}
            >
              {bulkBusy ? "Working…" : `Publish now (${eligiblePublish.length})`}
            </button>
            <button
              type="button"
              onClick={() => setConfirmBulkDelete(true)}
              disabled={bulkBusy}
              className="rounded-[16px] border border-red-300 bg-white px-4 py-2 text-[12px] font-bold text-red-600 transition hover:bg-red-50 disabled:opacity-50"
            >
              Remove ({selected.size})
            </button>
          </div>
        </div>
      )}

      {/* Upload dialog */}
      <MediaUploadDialog
        open={uploadOpen}
        locations={locations}
        defaultLocationId={selectedId}
        onClose={() => setUploadOpen(false)}
        onDone={(n) => { setUploadOpen(false); setNotice(n); void refreshItems(); }}
      />

      {/* Details dialog */}
      {viewing && (
        <MediaDetailsDialog
          item={viewing}
          onClose={() => setViewing(null)}
          onDelete={handleDeleteOne}
          onPublish={handlePublishOne}
          onUpdate={async (patch) => { await handleUpdateOne(viewing.id, patch); const r = await apiFetch(`/api/v1/media/${viewing.id}`); setViewing(normalizeMediaItem(r, 0)); }}
        />
      )}

      {/* Bulk delete confirm */}
      {confirmBulkDelete && (
        <Modal open onClose={() => setConfirmBulkDelete(false)} title={`Remove ${selected.size} item${selected.size === 1 ? "" : "s"}?`} subtitle="This removes them from your Sayvors library. Photos already live on Google stay live until you remove them in Live on Google." busy={bulkBusy} width="max-w-[460px]">
          <div className="space-y-4">
            <p className="text-[13px] text-ink/65">This cannot be undone.</p>
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={() => setConfirmBulkDelete(false)} disabled={bulkBusy} className="rounded-[20px] border border-ink/10 bg-white px-5 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05] disabled:opacity-50">Keep them</button>
              <button type="button" onClick={bulkDelete} disabled={bulkBusy} className="rounded-[20px] bg-red-600 px-5 py-2.5 text-[13px] font-bold text-white transition hover:bg-red-700 disabled:opacity-60">
                {bulkBusy ? "Removing…" : `Remove ${selected.size}`}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// Local normalize to avoid importing the dead MediaPage component at runtime.
function normalizeMediaItem(raw: unknown, i = 0): MediaItem {
  const m = (raw ?? {}) as Record<string, unknown>;
  const url = typeof m.image_url === "string" ? m.image_url : undefined;
  return {
    id: String(m.id ?? `m_${i}`),
    type: m.type === "VIDEO" ? "VIDEO" : "PHOTO",
    source: "OWN",
    category: String(m.category ?? "EXTERIOR"),
    thumbnailUrl: url,
    sourceUrl: url,
    views: 0,
    createdAt: String(m.created_at ?? m.createdAt ?? new Date().toISOString().slice(0, 10)).slice(0, 10),
    isProfile: m.is_profile === true,
    isCover: m.is_cover === true,
    status: (typeof m.status === "string" ? (m.status === "draft" ? "DRAFT" : m.status === "scheduled" ? "SCHEDULED" : m.status === "published" ? "PUBLISHED" : m.status === "failed" ? "FAILED" : "DRAFT") : "DRAFT") as MediaItem["status"],
    scheduledAt: m.scheduled_on ? String(m.scheduled_on) : undefined,
    error: typeof m.error === "string" ? m.error : undefined,
    method: typeof m.publish_method === "string" ? m.publish_method : undefined,
  };
}
