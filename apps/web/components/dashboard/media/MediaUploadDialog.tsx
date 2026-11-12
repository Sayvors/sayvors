"use client";

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import Modal from "./Modal";
import {
  MAX_UPLOAD_BYTES,
  validateMediaFile,
  validateImageDimensions,
  validateMediaUrl,
  validateSchedule,
  wallTimeToInstant,
  inspectImageFile,
  probeImageUrl,
  kindOfFile,
  formatBytes,
  mediaKindFromUrl,
  riyadhLabel,
  type MediaKind,
  type PublishMethod,
  type ImageDimensions,
} from "@/lib/media-validation";

interface LocationOption {
  id: string;
  name: string;
  channelId: string;
}

const GALLERY_CATEGORIES = [
  "EXTERIOR", "INTERIOR", "PRODUCT", "FOOD_AND_DRINK", "MENU",
  "COMMON_AREA", "ROOMS", "TEAM", "ADDITIONAL",
];

const METHOD_META: { key: PublishMethod; title: string; note: string; icon: string }[] = [
  { key: "post", title: "Google post", note: "Photo goes live inside a Google post with your caption.", icon: "📝" },
  { key: "gallery", title: "Photo gallery", note: "Adds the photo to the location gallery.", icon: "🖼" },
  { key: "profile", title: "Profile picture", note: "Replaces the Google profile picture (min 250×250px).", icon: "👤" },
  { key: "banner", title: "Banner (cover)", note: "Replaces the Google cover image (min 480×270px).", icon: "🏁" },
];

interface Props {
  open: boolean;
  locations: LocationOption[];
  defaultLocationId: string | null;
  defaultMethod?: PublishMethod;
  onClose: () => void;
  onDone: (notice: { kind: "ok" | "err"; text: string }) => void;
}

export default function MediaUploadDialog({ open, locations, defaultLocationId, defaultMethod, onClose, onDone }: Props) {
  const [locationId, setLocationId] = useState<string>(defaultLocationId ?? locations[0]?.id ?? "");
  const [mode, setMode] = useState<"file" | "url">("file");
  const [method, setMethod] = useState<PublishMethod>(defaultMethod ?? "post");
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [dims, setDims] = useState<ImageDimensions | null>(null);
  const [urlDraft, setUrlDraft] = useState("");
  const [urlDims, setUrlDims] = useState<ImageDimensions | null>(null);
  const [urlProbing, setUrlProbing] = useState(false);
  const [urlProbeError, setUrlProbeError] = useState<string | null>(null);
  const [category, setCategory] = useState("EXTERIOR");
  const [caption, setCaption] = useState("");
  const [schedule, setSchedule] = useState(false);
  const [scheduledAt, setScheduledAt] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [serverError, setServerError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [phase, setPhase] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (open) {
      setLocationId(defaultLocationId ?? locations[0]?.id ?? "");
      setMode("file");
      setMethod(defaultMethod ?? "post");
      setFile(null);
      setPreviewUrl(null);
      setDims(null);
      setUrlDraft("");
      setUrlDims(null);
      setUrlProbeError(null);
      setCategory("EXTERIOR");
      setCaption("");
      setSchedule(false);
      setScheduledAt("");
      setErrors([]);
      setWarnings([]);
      setServerError(null);
      setSubmitting(false);
      setPhase("");
    }
  }, [open, defaultLocationId, defaultMethod, locations]);

  useEffect(() => {
    if (!open) return;
    if (mode === "file" && file) {
      const issues = [
        ...validateMediaFile(file, method),
        ...(dims ? validateImageDimensions(dims, method) : []),
      ];
      setErrors(issues.filter((i) => i.level === "error").map((i) => i.message));
      setWarnings(issues.filter((i) => i.level === "warning").map((i) => i.message));
    } else if (mode === "url") {
      const issues = validateMediaUrl(urlDraft);
      if (urlDraft.trim() && urlDims) {
        issues.push(...validateImageDimensions(urlDims, method));
      }
      setErrors(issues.filter((i) => i.level === "error").map((i) => i.message));
      setWarnings(issues.filter((i) => i.level === "warning").map((i) => i.message));
    } else {
      setErrors([]);
      setWarnings([]);
    }
  }, [open, mode, file, dims, method, urlDraft, urlDims]);

  const kind: MediaKind | null = mode === "file" ? kindOfFile(file) : (urlDraft.trim() ? mediaKindFromUrl(urlDraft) : null);

  const handleFile = async (f: File) => {
    setServerError(null);
    setFile(f);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    const u = URL.createObjectURL(f);
    setPreviewUrl(u);
    setDims(null);
    const k = kindOfFile(f);
    if (k === "image") {
      try {
        const d = await inspectImageFile(f);
        setDims(d);
      } catch (e) {
        setErrors([e instanceof Error ? e.message : "Could not read that image."]);
      }
    } else {
      setDims(null);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    dragDepth.current = 0;
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) await handleFile(f);
  };

  const probeUrl = async () => {
    if (!urlDraft.trim()) return;
    const issues = validateMediaUrl(urlDraft);
    if (issues.some((i) => i.level === "error")) {
      setUrlProbeError(issues.find((i) => i.level === "error")!.message);
      return;
    }
    setUrlProbing(true);
    setUrlProbeError(null);
    setUrlDims(null);
    const k = mediaKindFromUrl(urlDraft);
    if (k === "image") {
      try {
        const d = await probeImageUrl(urlDraft.trim());
        setUrlDims(d);
      } catch (e) {
        setUrlProbeError(e instanceof Error ? e.message : "Could not load that image.");
      }
    } else {
      setUrlDims(null);
    }
    setUrlProbing(false);
  };

  const minScheduleValue = () => {
    const d = new Date(Date.now() + 5 * 60 * 1000);
    // format as local Riyadh wall time for datetime-local
    const pad = (n: number) => String(n).padStart(2, "0");
    // Use UTC+3 wall time
    const ms = d.getTime() + 3 * 60 * 60 * 1000 - d.getTimezoneOffset() * 60 * 1000; // not needed; browser local is fine
    void ms;
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };

  const submit = async () => {
    setServerError(null);
    const location = locations.find((l) => l.id === locationId);
    if (!location) {
      setServerError("Connect a Google location first.");
      return;
    }
    // validate
    const allErrors: string[] = [];
    if (mode === "file") {
      if (!file) allErrors.push("Choose a file to upload.");
      else {
        allErrors.push(...validateMediaFile(file, method).filter((i) => i.level === "error").map((i) => i.message));
        if (kindOfFile(file) === "image" && dims) {
          allErrors.push(...validateImageDimensions(dims, method).filter((i) => i.level === "error").map((i) => i.message));
        }
      }
    } else {
      allErrors.push(...validateMediaUrl(urlDraft).filter((i) => i.level === "error").map((i) => i.message));
      if (urlDraft.trim() && urlDims) {
        allErrors.push(...validateImageDimensions(urlDims, method).filter((i) => i.level === "error").map((i) => i.message));
      }
    }
    if (schedule) {
      allErrors.push(...validateSchedule(scheduledAt).map((i) => i.message));
    }
    if (allErrors.length) {
      setErrors(allErrors);
      return;
    }

    setSubmitting(true);
    try {
      let imageUrl = "";
      let mediaType: string = kind === "video" ? "VIDEO" : "PHOTO";
      if (mode === "file" && file) {
        setPhase("Uploading file…");
        const form = new FormData();
        form.append("file", file);
        const up = await apiFetch("/api/v1/media/upload", { method: "POST", body: form });
        imageUrl = up.image_url as string;
        if (up.type === "VIDEO" || up.type === "PHOTO") mediaType = up.type;
        if (!imageUrl) throw new Error("Upload returned no URL.");
      } else {
        imageUrl = urlDraft.trim();
      }

      setPhase(schedule ? "Scheduling…" : method === "post" ? "Publishing to Google…" : "Adding to Google…");
      const scheduledIso = schedule && scheduledAt ? wallTimeToInstant(scheduledAt)?.toISOString() ?? null : null;
      await apiFetch("/api/v1/media/", {
        method: "POST",
        body: JSON.stringify({
          listing_id: locationId,
          image_url: imageUrl,
          type: mediaType,
          category: method === "gallery" ? category : (method === "post" ? "EXTERIOR" : category),
          caption: method === "post" ? caption.trim() : "",
          action: schedule ? "schedule" : "publish",
          scheduled_on: scheduledIso,
          publish_method: method,
        }),
      });

      onDone({
        kind: "ok",
        text: schedule
          ? `Photo scheduled — goes live ${riyadhLabel(scheduledIso!)}.`
          : method === "post"
          ? "Photo published to Google."
          : method === "gallery"
          ? "Photo added to the Google gallery."
          : method === "profile"
          ? "Profile picture updated."
          : "Cover image updated.",
      });
      onClose();
    } catch (e) {
      setServerError(e instanceof Error ? e.message.slice(0, 240) : "Upload failed.");
    } finally {
      setSubmitting(false);
      setPhase("");
    }
  };

  const errorsShown = errors;
  const warningsShown = warnings;

  return (
    <Modal open={open} onClose={onClose} title="Upload media" subtitle="Add a photo or video to this Google location." busy={submitting} width="max-w-[640px]">
      <div className="space-y-5">
        {/* Location */}
        <div>
          <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-widest text-ink/55 dark:text-fog/55">Location</label>
          <select
            value={locationId}
            onChange={(e) => setLocationId(e.target.value)}
            className="w-full rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[13.5px] text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
          >
            {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </div>

        {/* Mode toggle */}
        <div className="flex rounded-[20px] bg-ink/[0.04] p-1 dark:bg-white/[0.06]">
          {(["file", "url"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={`flex-1 rounded-[16px] px-3 py-2 text-[12px] font-bold transition ${mode === m ? "bg-white text-ink shadow-[0_8px_20px_-14px_rgba(20,16,31,0.4)] dark:bg-[#1b1530] dark:text-fog" : "text-ink/55 dark:text-fog/55"}`}
            >
              {m === "file" ? "Upload file" : "From URL"}
            </button>
          ))}
        </div>

        {/* Media input */}
        {mode === "file" ? (
          <div>
            {!file ? (
              <div
                onDragEnter={(e) => { e.preventDefault(); dragDepth.current += 1; setDragging(true); }}
                onDragLeave={(e) => { e.preventDefault(); dragDepth.current -= 1; if (dragDepth.current <= 0) setDragging(false); }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={handleDrop}
                className={`flex flex-col items-center rounded-[24px] border-2 border-dashed px-6 py-10 text-center transition ${dragging ? "border-deep-violet bg-deep-violet/[0.05]" : "border-ink/15 bg-ink/[0.02]"}`}
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-deep-violet/10 text-[20px]">⬆</div>
                <p className="mt-3 text-[14px] font-bold text-ink dark:text-fog">Drop a photo or video here</p>
                <p className="mt-1 text-[12px] text-ink/55 dark:text-fog/55">JPG, PNG, WEBP, GIF, MP4, MOV — up to {MAX_UPLOAD_BYTES / 1024 / 1024}MB</p>
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="mt-4 rounded-[20px] bg-deep-violet px-5 py-2.5 text-[12px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90 active:translate-y-0.5 active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40"
                >
                  Browse files
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime"
                  className="hidden"
                  onChange={async (e) => { const f = e.target.files?.[0]; if (f) await handleFile(f); e.target.value = ""; }}
                />
              </div>
            ) : (
              <div className="flex items-start gap-4 rounded-[24px] border border-ink/10 bg-ink/[0.02] p-4 dark:border-white/[0.08]">
                <div className="h-24 w-24 shrink-0 overflow-hidden rounded-[16px] bg-ink/[0.06]">
                  {kind === "video" ? (
                    <video src={previewUrl ?? ""} className="h-full w-full object-cover" muted playsInline />
                  ) : previewUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={previewUrl} alt="" className="h-full w-full object-cover" />
                  ) : null}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13.5px] font-bold text-ink dark:text-fog">{file.name}</p>
                  <p className="mt-0.5 text-[12px] text-ink/55 dark:text-fog/55">
                    {kind === "video" ? "Video" : "Image"} · {formatBytes(file.size)}
                    {dims ? ` · ${dims.width}×${dims.height}px` : ""}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button type="button" onClick={() => fileInputRef.current?.click()} className="rounded-[16px] border border-ink/10 bg-white px-3 py-1.5 text-[12px] font-bold text-ink transition hover:bg-ink/[0.05] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:bg-white/[0.04] dark:text-fog">
                      Replace
                    </button>
                    <button type="button" onClick={() => { setFile(null); if (previewUrl) URL.revokeObjectURL(previewUrl); setPreviewUrl(null); setDims(null); }} className="rounded-[16px] border border-ink/10 bg-white px-3 py-1.5 text-[12px] font-bold text-red-600 transition hover:bg-red-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-red-400/40 dark:bg-white/[0.04]">
                      Remove
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-widest text-ink/55 dark:text-fog/55">Media URL</label>
            <div className="flex gap-2">
              <input
                value={urlDraft}
                onChange={(e) => { setUrlDraft(e.target.value); setUrlDims(null); setUrlProbeError(null); }}
                onBlur={() => { if (urlDraft.trim()) void probeUrl(); }}
                placeholder="https://…"
                className="min-w-0 flex-1 rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[13.5px] text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
              />
              <button
                type="button"
                onClick={probeUrl}
                disabled={urlProbing || !urlDraft.trim()}
                className="rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[12px] font-bold text-ink transition hover:bg-ink/[0.05] disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
              >
                {urlProbing ? <LogoLoader size={14} /> : "Check"}
              </button>
            </div>
            {urlDraft.trim() && (
              <p className="text-[11.5px] text-ink/55 dark:text-fog/55">
                {urlProbing
                  ? "Checking link…"
                  : urlProbeError
                  ? <span className="text-red-600">{urlProbeError}</span>
                  : urlDims
                  ? `Image · ${urlDims.width}×${urlDims.height}px`
                  : "Link not checked yet — click Check."}
              </p>
            )}
          </div>
        )}

        {/* Method selection */}
        <div>
          <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-widest text-ink/55 dark:text-fog/55">Publish to Google as</label>
          <div className="grid gap-2 sm:grid-cols-2">
            {METHOD_META.map((m) => {
              const disabled = kind === "video" && m.key !== "post";
              const selected = method === m.key;
              return (
                <button
                  key={m.key}
                  type="button"
                  disabled={disabled}
                  onClick={() => setMethod(m.key)}
                  aria-pressed={selected}
                  className={`flex items-start gap-3 rounded-[20px] border p-3 text-left transition ${disabled ? "cursor-not-allowed border-ink/10 bg-ink/[0.02] opacity-50" : selected ? "border-deep-violet bg-deep-violet/[0.06]" : "border-ink/10 bg-white hover:border-deep-violet/40 dark:bg-white/[0.04]"}`}
                >
                  <span className="text-[18px]" aria-hidden>{m.icon}</span>
                  <span className="min-w-0">
                    <span className="block text-[13px] font-bold text-ink dark:text-fog">{m.title}</span>
                    <span className="block text-[11px] text-ink/55 dark:text-fog/55">{m.note}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Category (gallery only) */}
        {method === "gallery" && (
          <div>
            <label className="mb-1.5 block text-[12px] font-bold uppercase tracking-widest text-ink/55 dark:text-fog/55">Category</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="w-full rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[13.5px] text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
            >
              {GALLERY_CATEGORIES.map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
            </select>
          </div>
        )}

        {/* Caption (post only) */}
        {method === "post" && (
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-[12px] font-bold uppercase tracking-widest text-ink/55 dark:text-fog/55">Caption</label>
              <span className="text-[11px] text-ink/45 dark:text-fog/45">{caption.length} / 500</span>
            </div>
            <textarea
              value={caption}
              onChange={(e) => setCaption(e.target.value)}
              maxLength={500}
              rows={3}
              placeholder="Optional caption for the Google post…"
              className="w-full resize-y rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[13.5px] text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
            />
          </div>
        )}

        {/* Schedule */}
        <div className="rounded-[20px] border border-ink/10 bg-ink/[0.02] p-4 dark:border-white/[0.08]">
          <label className="flex items-center justify-between gap-3">
            <span>
              <span className="block text-[13.5px] font-bold text-ink dark:text-fog">Schedule for later</span>
              <span className="block text-[11.5px] text-ink/55 dark:text-fog/55">Photo goes live on Google at that time (Riyadh, UTC+3).</span>
            </span>
            <button
              type="button"
              role="switch"
              aria-checked={schedule}
              onClick={() => {
                if (kind === "video") return;
                setSchedule((s) => !s);
              }}
              disabled={kind === "video"}
              className={`relative h-7 w-12 shrink-0 rounded-full transition ${schedule ? "bg-deep-violet" : "bg-ink/20"} ${kind === "video" ? "cursor-not-allowed opacity-50" : ""}`}
            >
              <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all ${schedule ? "left-6" : "left-1"}`} />
            </button>
          </label>
          {schedule && (
            <input
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
              min={minScheduleValue()}
              className="mt-3 w-full rounded-[20px] border border-ink/10 bg-white px-4 py-3 text-[13.5px] text-ink outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 dark:bg-white/[0.04] dark:text-fog"
            />
          )}
          {kind === "video" && (
            <p className="mt-2 text-[11.5px] text-amber-700 dark:text-amber-400">Videos can't be scheduled — they save to your library only.</p>
          )}
        </div>

        {/* Issues */}
        {(errorsShown.length > 0 || warningsShown.length > 0 || serverError) && (
          <div className="space-y-2">
            {serverError && (
              <p role="alert" className="rounded-[16px] border border-red-500/40 bg-red-500/10 px-4 py-3 text-[12.5px] font-medium text-red-700 dark:text-red-400">{serverError}</p>
            )}
            {errorsShown.map((m, i) => (
              <p key={`e${i}`} role="alert" className="rounded-[16px] border border-red-500/40 bg-red-500/10 px-4 py-3 text-[12.5px] font-medium text-red-700 dark:text-red-400">{m}</p>
            ))}
            {warningsShown.map((m, i) => (
              <p key={`w${i}`} className="rounded-[16px] border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-[12.5px] font-medium text-amber-700 dark:text-amber-400">{m}</p>
            ))}
          </div>
        )}

        <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-[20px] border border-ink/10 bg-white px-5 py-2.5 text-[13px] font-bold text-ink transition hover:bg-ink/[0.05] disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 dark:bg-white/[0.04] dark:text-fog"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="inline-flex items-center justify-center gap-2 rounded-[20px] bg-deep-violet px-6 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90 active:translate-y-0.5 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40"
          >
            {submitting ? <><LogoLoader size={14} /> {phase || "Saving…"}</> : schedule ? "Schedule photo" : "Publish photo"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
