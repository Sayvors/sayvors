"use client";

import { useEffect, useRef, useState } from "react";
import { CROP_ASPECT } from "./CropFrame";
import { MAX_MEDIA_MB, type CropState } from "./types";
import { inspectImageFile, probeImageUrl, normalizePickedFile, canDecodeInBrowser, ALLOWED_IMAGE_EXT, ALLOWED_VIDEO_EXT } from "@/lib/media-validation";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { apiFetch, apiFetchBlob } from "@/lib/api-rag";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

export interface ThumbCrop {
  cropKey: CropState["key"];
  zoom: number;
  x: number;
  y: number;
}

export function formatBytes(n: number | undefined, t?: { mb: string; kb: string }, fmt?: (n: number) => string): string {
  if (!n || n <= 0) return "";
  const f = fmt ?? ((v: number) => String(v));
  if (n >= 1024 * 1024) return fill(t?.mb ?? "{n}MB", { n: f(Math.round((n / 1024 / 1024) * 10) / 10) });
  return fill(t?.kb ?? "{n}KB", { n: f(Math.round(n / 1024)) });
}

function thumbBox(cropKey: CropState["key"]): { w: number; h: number } {
  if (cropKey === "orig") return { w: 112, h: 112 };
  const aspect = CROP_ASPECT[cropKey as Exclude<CropState["key"], "orig">];
  return aspect >= 1 ? { w: Math.round(96 * aspect), h: 96 } : { w: 84, h: Math.round(84 / aspect) };
}

export default function MediaSink({
  media,
  onPick,
  onClear,
  thumb = null,
  thumbLabel = "",
  platforms = [],
  replaceSignal = 0,
}: {
  media: { type: "image" | "video" | null; url: string; fileName?: string; sizeBytes?: number } | null;
  onPick: (type: "image" | "video", url: string, fileName?: string, sizeBytes?: number, file?: File, width?: number, height?: number) => void;
  onClear: () => void;
  thumb?: ThumbCrop | null;
  thumbLabel?: string;
  /** Destinations this media will be published to — drives Google's stricter limits. */
  platforms?: string[];
  /** Bumped by the parent to open the file picker from anywhere (an AI
      verdict or a publish error) — the one-click route back to fixing the
      photo, instead of stepping back through the wizard. */
  replaceSignal?: number;
}) {
  const [dropping, setDropping] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [scanning, setScanning] = useState<string | null>(null);
  const [source, setSource] = useState<"upload" | "link" | "library">("upload");
  const [libraryItems, setLibraryItems] = useState<{ id: string; url: string; type: "image" | "video"; label: string; sizeBytes?: number }[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const { t, locale } = useI18n();
  const md = t.publish.media;
  const pc = t.publish.composer;
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const fileInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  // Google posts take a single photo, max 5MB, min 250px, and no video.
  const hasGoogle = platforms.includes("google_reviews");
  const maxMb = hasGoogle ? 5 : MAX_MEDIA_MB;

  // Parent-driven "replace this photo": open the OS picker directly.
  useEffect(() => {
    if (replaceSignal > 0) fileInput.current?.click();
  }, [replaceSignal]);

  const aspect = thumb && thumb.cropKey !== "orig" ? CROP_ASPECT[thumb.cropKey as Exclude<CropState["key"], "orig">] : null;
  const box = thumbBox(thumb?.cropKey ?? "orig");
  const cropStyle = aspect
    ? { transform: `scale(${Math.max(thumb?.zoom ?? 1, 1.08)}) translate(${(thumb?.x ?? 0) / 12}px, ${(thumb?.y ?? 0) / 12}px)` }
    : undefined;

  const acceptFiles = async (files: FileList | null) => {
    setError(null);
    setInfo(null);
    setScanning(null);
    const file = files?.[0];
    if (!file) return;
    if (file.size > maxMb * 1024 * 1024) {
      setError(hasGoogle ? pc.googleSize : fill(md.tooBig, { n: fmt(maxMb) }));
      return;
    }
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    const isImageExt = ALLOWED_IMAGE_EXT.includes(ext);
    const isVideoExt = ALLOWED_VIDEO_EXT.includes(ext);
    const kind: "image" | "video" | null =
      isVideoExt || file.type.startsWith("video/") ? "video" :
      isImageExt || file.type.startsWith("image/") ? "image" : null;
    if (!kind || (!isImageExt && !isVideoExt && !file.type.startsWith("image/") && !file.type.startsWith("video/"))) {
      setError(md.badType);
      return;
    }
    // Reject types the server would reject, even if the MIME looks right.
    if (kind === "image" && !isImageExt && !ALLOWED_IMAGE_EXT.includes(ext)) {
      setError(md.badType);
      return;
    }
    if (kind === "video" && !isVideoExt) {
      setError(md.badType);
      return;
    }
    if (hasGoogle && kind === "video") {
      setError(pc.googleVideo);
      return;
    }
    // Downloads from WhatsApp/phones often carry a lying extension or a
    // format Google refuses (HEIC/AVIF). Fix or convert NOW, at pick time,
    // so it can never surface as a publish failure after everything is set.
    // Every stage announces itself: a silent pipeline reads as broken.
    const norm = await (async () => {
      setScanning("Checking the file…");
      try {
        return await normalizePickedFile(file);
      } finally {
        setScanning(null);
      }
    })();
    if (!norm.ok) {
      setError(norm.error);
      return;
    }
    if (norm.note) setInfo(norm.note);
    let picked = norm.file;
    // A valid file the browser still cannot rasterise (CMYK JPEG, oversized
    // scan) would show an empty crop frame and publish uncropped. Pillow
    // decodes what browsers cannot, so ask the server for a usable copy.
    if (kind === "image" && !(await canDecodeInBrowser(picked))) {
      setScanning("Preparing the photo…");
      try {
        const form = new FormData();
        form.append("file", picked);
        const blob = await apiFetchBlob("/api/v1/media/convert", { method: "POST", body: form });
        const ext = blob.type === "image/png" ? "png" : "jpg";
        picked = new File(
          [blob],
          `${(picked.name.replace(/\.[^.]+$/, "") || "photo")}-ready.${ext}`,
          { type: blob.type },
        );
        setInfo(
          "Prepared on Sayvors servers — your browser can't display the original file, but this copy previews, crops and publishes normally.",
        );
      } catch (e) {
        setError(
          e instanceof Error
            ? e.message
            : "That photo can't be prepared for publishing. Export it as JPG or PNG and try again.",
        );
        return;
      } finally {
        setScanning(null);
      }
    }
    let width: number | undefined;
    let height: number | undefined;
    if (kind === "image") {
      try {
        const d = await inspectImageFile(picked);
        width = d.width; height = d.height;
        if (width < 250 || height < 250) {
          setError(pc.googleSmall);
          return;
        }
      } catch {
        // keep going; server will validate
      }
    }
    onPick(kind, URL.createObjectURL(picked), picked.name, picked.size, picked, width, height);
  };

  const openLibrary = async () => {
    setSource("library");
    setError(null);
    if (libraryItems.length > 0 || libraryLoading) return;
    setLibraryLoading(true);
    try {
      const data = await apiFetch("/api/v1/media?limit=60");
      const list = Array.isArray(data) ? data : ((data as { media?: unknown[] })?.media ?? []);
      setLibraryItems(
        list.map((m) => {
          const row = m as Record<string, unknown>;
          const url = typeof row.image_url === "string" ? row.image_url : "";
          return {
            id: String(row.id ?? ""),
            url,
            type: row.type === "VIDEO" ? ("video" as const) : ("image" as const),
            label: String(row.category ?? "Media").replace(/_/g, " "),
            sizeBytes: typeof row.size === "number" ? row.size : undefined,
          };
        }).filter((m) => m.url),
      );
    } catch {
      setLibraryError("Couldn't load your library. Try again.");
    } finally {
      setLibraryLoading(false);
    }
  };

  const pickFromLibrary = (item: { id: string; url: string; type: "image" | "video"; label: string; sizeBytes?: number }) => {
    if (item.type === "image") {
      probeImageUrl(item.url).then((d) => {
        if (d.width < 250 || d.height < 250) {
          setError("That library image is below Google's 250×250px minimum — pick a larger one.");
          return;
        }
        onPick("image", item.url, item.label, item.sizeBytes, undefined, d.width, d.height);
      }).catch(() => {
        onPick("image", item.url, item.label, item.sizeBytes);
      });
    } else {
      onPick("video", item.url, item.label, item.sizeBytes);
    }
  };

  const addUrl = async () => {
    const value = urlDraft.trim();
    if (!value) return;
    setError(null);
    let parsed: URL;
    try {
      parsed = new URL(value);
    } catch {
      setError(md.notUrl);
      return;
    }
    if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
      setError(md.badUrl);
      return;
    }
    if (parsed.protocol === "http:") {
      setError("Use an https link — Google and some networks refuse plain http.");
      return;
    }
    const kind = /\.(mp4|mov|m4v)(\?|$)/i.test(parsed.pathname) ? "video" : "image";
    if (hasGoogle && kind === "video") {
      setError(pc.googleVideo);
      return;
    }
    let width: number | undefined;
    let height: number | undefined;
    if (kind === "image") {
      try {
        const d = await probeImageUrl(value);
        width = d.width; height = d.height;
        if (width < 250 || height < 250) {
          setError(pc.googleSmall);
          return;
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not load that image.");
        return;
      }
    }
    onPick(kind, value, undefined, undefined, undefined, width, height);
    setUrlDraft("");
  };

  const tabClass = (active: boolean) =>
    `flex-1 rounded-[20px] px-3 py-2 text-[12px] font-bold transition duration-200 active:scale-[0.98] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
      active
        ? "bg-[var(--ui-surface)] text-[var(--ui-ink)] shadow-[0_8px_18px_-12px_rgba(61,29,110,0.55)]"
        : "text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)]"
    }`;

  return (
    <div className="space-y-3">
      {media ? (
        /* Chosen media: one clear card with the preview, details and actions. */
        <div className="flex flex-wrap items-center gap-4 rounded-[24px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5 shadow-[0_12px_28px_-22px_rgba(61,29,110,0.45)]">
          <div
            className="relative shrink-0 overflow-hidden rounded-[20px] border border-[var(--ui-line)] bg-[var(--ui-surface)] shadow-[0_12px_28px_-20px_rgba(61,29,110,0.5)] transition-[width,height] duration-200"
            style={{ width: box.w, height: box.h }}
          >
            {media.type === "video" ? (
              <video
                src={media.url}
                muted
                playsInline
                className="h-full w-full object-cover"
                style={cropStyle}
              />
            ) : (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img src={media.url} alt="" className="h-full w-full object-cover" style={cropStyle} />
            )}
          </div>
          <div className="min-w-[9rem] flex-1">
            <p className="truncate text-[13px] font-bold text-[var(--ui-ink)]">
              {media.fileName ?? media.url}
            </p>
            <p className="mt-0.5 text-[11.5px] text-[var(--ui-ink-2)]">
              {media.type === "video" ? md.video : md.image}
              {media.sizeBytes ? ` · ${formatBytes(media.sizeBytes)}` : ""}
            </p>
            {thumbLabel && (
              <p className="mt-1 text-[11px] font-semibold text-[var(--ui-ink)]">
                {fill(md.frameMirrors, { label: thumbLabel })}
              </p>
            )}
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className="clay-btn-secondary px-3 py-1.5 text-[11px] font-semibold focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
              >
                {md.replace}
              </button>
              <button
                type="button"
                onClick={onClear}
                className="rounded-[20px] px-3 py-1.5 text-[11px] font-semibold text-red-600 outline-none transition hover:bg-red-500/10 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] dark:text-red-400"
              >
                {md.removeMedia}
              </button>
            </div>
          </div>
        </div>
      ) : (
        /* Three standard sources, one tab at a time. */
        <div>
          <div className="flex gap-1 rounded-[24px] bg-[var(--ui-sunken)] p-1" role="tablist" aria-label={md.pasteAria}>
            <button type="button" role="tab" aria-selected={source === "upload"} onClick={() => setSource("upload")} className={tabClass(source === "upload")}>
              {md.tabUpload}
            </button>
            <button type="button" role="tab" aria-selected={source === "link"} onClick={() => setSource("link")} className={tabClass(source === "link")}>
              {md.tabLink}
            </button>
            <button type="button" role="tab" aria-selected={source === "library"} onClick={openLibrary} className={tabClass(source === "library")}>
              {md.tabLibrary}
            </button>
          </div>

          {source === "upload" && (
            <div
              role="tabpanel"
              onDragEnter={(e) => {
                e.preventDefault();
                dragDepth.current += 1;
                setDropping(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                dragDepth.current -= 1;
                if (dragDepth.current <= 0) setDropping(false);
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                dragDepth.current = 0;
                setDropping(false);
                acceptFiles(e.dataTransfer.files);
              }}
              className={`mt-3 flex flex-col items-center rounded-[28px] border-2 border-dashed bg-[var(--ui-sunken)] px-4 py-8 text-center transition duration-200 ${
                dropping
                  ? "border-[var(--ui-ink)] bg-[var(--ui-ink)]/[0.04]"
                  : "border-[var(--ui-line-strong)] hover:border-[var(--ui-ink)]/40"
              }`}
            >
              <span className="flex h-14 w-14 items-center justify-center rounded-[20px] bg-[var(--ui-surface)] text-[var(--ui-ink)] shadow-[0_10px_20px_-14px_rgba(61,29,110,0.6)]">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6" aria-hidden>
                  <rect x="3" y="3" width="18" height="18" rx="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <path d="M21 15l-5-5L5 21" />
                </svg>
              </span>
              <p className="mt-3 text-[14px] font-bold text-[var(--ui-ink)]">{md.dropTitle}</p>
              <p className="mt-1 text-[11.5px] text-[var(--ui-ink-2)]">{fill(md.dropSub, { n: fmt(maxMb) })}</p>
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className="clay-btn-primary mt-4 px-5 py-2.5 text-[12px] font-bold focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
              >
                {md.browse}
              </button>
            </div>
          )}

          {source === "link" && (
            <div role="tabpanel" className="mt-3 rounded-[24px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5">
              <p className="mb-2 text-[11.5px] text-[var(--ui-ink-2)]">{md.urlHint}</p>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="url"
                  value={urlDraft}
                  onChange={(e) => setUrlDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      addUrl();
                    }
                  }}
                  placeholder={md.pastePh}
                  aria-label={md.pasteAria}
                  className="clay-input min-w-[12rem] flex-1 px-3 py-2 text-[12px] text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
                />
                <button
                  type="button"
                  onClick={addUrl}
                  disabled={!urlDraft.trim()}
                  className="clay-btn-primary px-4 py-2 text-[12px] font-bold disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                >
                  {md.add}
                </button>
              </div>
            </div>
          )}

          {source === "library" && (
            <div role="tabpanel" className="mt-3 rounded-[24px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-3.5">
              {libraryLoading ? (
                <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{md.libraryLoading}</p>
              ) : libraryError ? (
                <div className="flex items-center justify-between gap-2 py-2">
                  <p className="text-[12px] font-medium text-red-600 dark:text-red-400">{md.libraryError}</p>
                  <button type="button" onClick={openLibrary} className="clay-btn-secondary px-3 py-1.5 text-[11px] font-semibold focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]">
                    {md.libraryRetry}
                  </button>
                </div>
              ) : libraryItems.length === 0 ? (
                <p className="py-6 text-center text-[12px] text-[var(--ui-ink-2)]">{md.libraryEmpty}</p>
              ) : (
                <div className="grid max-h-64 grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-4">
                  {libraryItems.map((it) => (
                    <button
                      key={it.id}
                      type="button"
                      onClick={() => pickFromLibrary(it)}
                      title={`${it.label} — ${md.libraryChoose}`}
                      className="group relative aspect-square overflow-hidden rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-surface)] transition duration-200 hover:-translate-y-0.5 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
                    >
                      {it.type === "video" ? (
                        <video src={it.url} muted playsInline className="h-full w-full object-cover" />
                      ) : (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={it.url} alt={it.label} className="h-full w-full object-cover" loading="lazy" />
                      )}
                      <span className="absolute inset-x-0 bottom-0 truncate bg-black/55 px-1 py-0.5 text-[9px] font-semibold text-white opacity-0 transition group-hover:opacity-100">
                        {it.label}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {scanning && (
        <p role="status" className="flex items-center gap-2 text-[12px] font-semibold text-deep-violet dark:text-fog">
          <svg className="h-3.5 w-3.5 shrink-0 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
            <path d="M12 3a9 9 0 1 0 9 9" strokeLinecap="round" />
          </svg>
          {scanning}
        </p>
      )}
      {error && (
        <p role="alert" className="text-[12px] font-semibold text-red-600 dark:text-red-400">
          {error}
        </p>
      )}
      {info && !error && !scanning && (
        <p role="status" className="text-[12px] font-semibold text-deep-violet dark:text-fog">
          {info}
        </p>
      )}

      <input
        ref={fileInput}
        type="file"
        accept={hasGoogle
          ? "image/jpeg,image/png,image/webp,image/gif"
          : "image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime"}
        hidden
        onChange={(e) => {
          void acceptFiles(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
