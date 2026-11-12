"use client";

import { useRef, useState } from "react";
import { CROP_ASPECT } from "./CropFrame";
import { MAX_MEDIA_MB, type CropState } from "./types";
import { inspectImageFile, probeImageUrl, ALLOWED_IMAGE_EXT, ALLOWED_VIDEO_EXT } from "@/lib/media-validation";
import { useI18n } from "@/lib/i18n/I18nProvider";

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
}: {
  media: { type: "image" | "video" | null; url: string; fileName?: string; sizeBytes?: number } | null;
  onPick: (type: "image" | "video", url: string, fileName?: string, sizeBytes?: number, file?: File, width?: number, height?: number) => void;
  onClear: () => void;
  thumb?: ThumbCrop | null;
  thumbLabel?: string;
}) {
  const [dropping, setDropping] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const { t, locale } = useI18n();
  const md = t.publish.media;
  const fmt = (n: number) => new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const fileInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

  const aspect = thumb && thumb.cropKey !== "orig" ? CROP_ASPECT[thumb.cropKey as Exclude<CropState["key"], "orig">] : null;
  const box = thumbBox(thumb?.cropKey ?? "orig");

  const acceptFiles = async (files: FileList | null) => {
    setError(null);
    const file = files?.[0];
    if (!file) return;
    if (file.size > MAX_MEDIA_MB * 1024 * 1024) {
      setError(fill(md.tooBig, { n: fmt(MAX_MEDIA_MB) }));
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
    let width: number | undefined;
    let height: number | undefined;
    if (kind === "image") {
      try {
        const d = await inspectImageFile(file);
        width = d.width; height = d.height;
        if (width < 250 || height < 250) {
          setError("That image is below Google's 250×250px minimum — Google may reject it.");
          return;
        }
      } catch {
        // keep going; server will validate
      }
    }
    onPick(kind, URL.createObjectURL(file), file.name, file.size, file, width, height);
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
    let width: number | undefined;
    let height: number | undefined;
    if (kind === "image") {
      try {
        const d = await probeImageUrl(value);
        width = d.width; height = d.height;
        if (width < 250 || height < 250) {
          setError("That image is below Google's 250×250px minimum — Google may reject it.");
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

  return (
    <div>
      {media ? (
        <div className="flex flex-wrap items-start gap-3">
          <div
            className="relative shrink-0 overflow-hidden rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] transition-[width,height] duration-200"
            style={{ width: box.w, height: box.h }}
          >
            {media.type === "video" ? (
              <video
                src={media.url}
                muted
                playsInline
                className="h-full w-full object-cover"
                style={
                  aspect
                    ? {
                        transform: `scale(${Math.max(thumb?.zoom ?? 1, 1.08)}) translate(${(thumb?.x ?? 0) / 12}px, ${(thumb?.y ?? 0) / 12}px)`,
                      }
                    : undefined
                }
              />
            ) : (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={media.url}
                alt=""
                className="h-full w-full object-cover"
                style={
                  aspect
                    ? {
                        transform: `scale(${Math.max(thumb?.zoom ?? 1, 1.08)}) translate(${(thumb?.x ?? 0) / 12}px, ${(thumb?.y ?? 0) / 12}px)`,
                      }
                    : undefined
                }
              />
            )}
            <button
              type="button"
              onClick={onClear}
              aria-label={md.removeMedia}
              className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-[rgba(0,0,0,0.65)] text-[13px] font-bold text-white outline-none transition hover:bg-black focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-white"
            >
              ×
            </button>
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-semibold text-[var(--ui-ink)]">
              {media.fileName ?? media.url}
            </p>
            <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
              {media.type === "video" ? md.video : md.image}
              {media.sizeBytes ? ` · ${formatBytes(media.sizeBytes)}` : ""}
            </p>
            {thumbLabel && (
              <p className="mt-1 text-[11px] font-semibold text-[var(--ui-ink)]">
                {fill(md.frameMirrors, { label: thumbLabel })}
              </p>
            )}
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="mt-2 rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-line)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
            >
              {md.replace}
            </button>
          </div>
        </div>
      ) : (
        <div
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
          className={`flex flex-col items-center rounded-[12px] border-2 border-dashed px-4 py-7 text-center transition ${
            dropping
              ? "border-[var(--ui-ink)] bg-[var(--ui-ink)]/[0.04]"
              : "border-[var(--ui-line)]"
          }`}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 text-[var(--ui-ink-2)]" aria-hidden>
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="M21 15l-5-5L5 21" />
          </svg>
          <p className="mt-2 text-[13px] font-semibold text-[var(--ui-ink)]">
            {md.dropTitle}
          </p>
          <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
            {fill(md.dropSub, { n: fmt(MAX_MEDIA_MB) })}
          </p>
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="mt-3 rounded-[10px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-4 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-line)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            {md.browse}
          </button>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
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
          className="min-w-[12rem] flex-1 rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
        />
        <button
          type="button"
          onClick={addUrl}
          disabled={!urlDraft.trim()}
          className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-line)] disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        >
{md.add}
        </button>
      </div>

      {error && (
        <p role="alert" className="mt-2 text-[12px] font-semibold text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      <input
        ref={fileInput}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm,video/quicktime"
        hidden
        onChange={(e) => {
          void acceptFiles(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
