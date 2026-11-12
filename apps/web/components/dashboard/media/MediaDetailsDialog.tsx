"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import Modal from "./Modal";
import type { MediaItem } from "../MediaPage";

interface Props {
  item: MediaItem;
  onClose: () => void;
  onDelete: (id: string) => void;
  onPublish: (id: string) => void;
  onUpdate: (patch: Record<string, unknown>) => Promise<void>;
}

const GALLERY_CATEGORIES = ["EXTERIOR", "INTERIOR", "PRODUCT", "FOOD_AND_DRINK", "MENU", "COMMON_AREA", "ROOMS", "TEAM", "ADDITIONAL"];
const METHODS = [
  { key: "post", label: "Google post" },
  { key: "gallery", label: "Photo gallery" },
  { key: "profile", label: "Profile picture" },
  { key: "banner", label: "Banner (cover)" },
];

const STATUS_TONE: Record<string, string> = {
  DRAFT: "bg-sky-100 text-sky-700",
  SCHEDULED: "bg-amber-100 text-amber-700",
  PUBLISHED: "bg-emerald-100 text-emerald-700",
  FAILED: "bg-red-100 text-red-700",
};

export default function MediaDetailsDialog({ item, onClose, onDelete, onPublish, onUpdate }: Props) {
  const [editing, setEditing] = useState(item.status !== "PUBLISHED");
  const [category, setCategory] = useState(item.category);
  const [caption, setCaption] = useState("");
  const [method, setMethod] = useState(item.method ?? "post");
  const [saving, setSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // fetch full item (caption not in list? list includes caption? MediaOut has caption)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const full = await apiFetch(`/api/v1/media/${item.id}`);
        if (cancelled) return;
        if (typeof full?.caption === "string") setCaption(full.caption);
        if (typeof full?.category === "string") setCategory(full.category);
        if (typeof full?.publish_method === "string") setMethod(full.publish_method);
      } catch { /* keep defaults */ }
    })();
    return () => { cancelled = true; };
  }, [item.id]);

  const published = item.status === "PUBLISHED";
  const canPublish = !published && item.type === "PHOTO";

  const save = async () => {
    setError(null);
    setSaving(true);
    try {
      const patch: Record<string, unknown> = {};
      if (category !== item.category) patch.category = category;
      if (method !== item.method) patch.publish_method = method;
      if (caption) patch.caption = caption;
      if (Object.keys(patch).length) await onUpdate(patch);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const publishNow = async () => {
    setError(null);
    setPublishing(true);
    try {
      await onPublish(item.id);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message.slice(0, 200) : "Publish failed.");
    } finally {
      setPublishing(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="Media details" subtitle={item.category.replace(/_/g, " ")} busy={saving || publishing} width="max-w-[520px]">
      <div className="space-y-5">
        <div className="overflow-hidden rounded-[24px] bg-ink/[0.04]">
          {item.thumbnailUrl || item.sourceUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={item.thumbnailUrl || item.sourceUrl} alt="" className="max-h-72 w-full object-contain" />
          ) : (
            <div className="flex h-48 items-center justify-center text-[40px] text-ink/20">🖼</div>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide ${STATUS_TONE[item.status ?? "DRAFT"] ?? "bg-ink/10 text-ink/60"}`}>{item.status ?? "DRAFT"}</span>
          {item.isProfile && <span className="rounded-full bg-deep-violet px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-white">Profile</span>}
          {item.isCover && <span className="rounded-full bg-emerald-600 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide text-white">Cover</span>}
          <span className="text-[11.5px] text-ink/50">{item.type === "VIDEO" ? "Video" : "Photo"}</span>
        </div>

        <dl className="grid grid-cols-[7rem_1fr] gap-x-3 gap-y-2 text-[13px]">
          <dt className="text-ink/50">Uploaded</dt><dd className="text-ink">{item.createdAt}</dd>
          <dt className="text-ink/50">Method</dt><dd className="text-ink">{(item.method ?? "post").replace(/_/g, " ")}</dd>
          {item.scheduledAt && (<><dt className="text-ink/50">Scheduled</dt><dd className="text-ink">{new Date(item.scheduledAt).toLocaleString()}</dd></>)}
          {item.error && (<><dt className="text-ink/50">Error</dt><dd className="text-red-600">{item.error}</dd></>)}
        </dl>

        {published && (
          <p className="rounded-[16px] border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-[12.5px] text-amber-700">
            This photo is live on Google. You can delete it from your library here, but to remove it from Google use the Live on Google tab.
          </p>
        )}

        {!published && (
          <div className="space-y-3">
            <div>
              <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-widest text-ink/55">Destination</label>
              <select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[13.5px] text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25">
                {METHODS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
            </div>
            {method === "gallery" && (
              <div>
                <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-widest text-ink/55">Category</label>
                <select value={category} onChange={(e) => setCategory(e.target.value)} className="w-full rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[13.5px] text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25">
                  {GALLERY_CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
                </select>
              </div>
            )}
            {method === "post" && (
              <div>
                <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-widest text-ink/55">Caption</label>
                <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} maxLength={500} className="w-full resize-y rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[13.5px] text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25" />
              </div>
            )}
          </div>
        )}

        {error && <p role="alert" className="rounded-[16px] border border-red-500/40 bg-red-500/10 px-4 py-3 text-[12.5px] font-medium text-red-700">{error}</p>}

        <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
          {!published && (
            <button type="button" onClick={save} disabled={saving} className="rounded-[20px] border border-ink/10 bg-white px-5 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05] disabled:opacity-50">
              {saving ? "Saving…" : "Save changes"}
            </button>
          )}
          {canPublish && (
            <button type="button" onClick={publishNow} disabled={publishing} className="rounded-[20px] bg-deep-violet px-5 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90 disabled:opacity-60">
              {publishing ? "Publishing…" : "Publish now"}
            </button>
          )}
          <button type="button" onClick={() => setConfirmDelete(true)} className="rounded-[20px] border border-red-300 bg-white px-5 py-2.5 text-[13px] font-bold text-red-600 transition hover:bg-red-50">
            Delete from library
          </button>
        </div>

        {confirmDelete && (
          <Modal open onClose={() => setConfirmDelete(false)} title="Delete this media?" subtitle="Removes it from your Sayvors library. If it is already live on Google, remove it in Live on Google too." busy={false} width="max-w-[420px]">
            <div className="space-y-4">
              <p className="text-[13px] text-ink/65">This cannot be undone.</p>
              <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                <button type="button" onClick={() => setConfirmDelete(false)} className="rounded-[20px] border border-ink/10 bg-white px-5 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05]">Keep it</button>
                <button type="button" onClick={() => { setConfirmDelete(false); onDelete(item.id); }} className="rounded-[20px] bg-red-600 px-5 py-2.5 text-[13px] font-bold text-white transition hover:bg-red-700">Delete</button>
              </div>
            </div>
          </Modal>
        )}
      </div>
    </Modal>
  );
}
