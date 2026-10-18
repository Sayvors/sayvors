"use client";

import { useRef, useState } from "react";
import { CROP_ASPECT } from "./CropFrame";
import { MAX_MEDIA_MB, type CropState } from "./types";

export interface ThumbCrop {
  cropKey: CropState["key"];
  zoom: number;
  x: number;
  y: number;
}

export function formatBytes(n: number | undefined): string {
  if (!n || n <= 0) return "";
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}MB`;
  return `${Math.round(n / 1024)}KB`;
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
  onPick: (type: "image" | "video", url: string, fileName?: string, sizeBytes?: number) => void;
  onClear: () => void;
  thumb?: ThumbCrop | null;
  thumbLabel?: string;
}) {
  const [dropping, setDropping] = useState(false);
  const [urlDraft, setUrlDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);

  const aspect = thumb && thumb.cropKey !== "orig" ? CROP_ASPECT[thumb.cropKey as Exclude<CropState["key"], "orig">] : null;
  const box = thumbBox(thumb?.cropKey ?? "orig");

  const acceptFiles = (files: FileList | null) => {
    setError(null);
    const file = files?.[0];
    if (!file) return;
    if (file.size > MAX_MEDIA_MB * 1024 * 1024) {
      setError(`Files up to ${MAX_MEDIA_MB}MB only.`);
      return;
    }
    const kind = file.type.startsWith("video/") ? "video" : file.type.startsWith("image/") ? "image" : null;
    if (!kind) {
      setError("Images or video only.");
      return;
    }
    onPick(kind, URL.createObjectURL(file), file.name, file.size);
  };

  const addUrl = () => {
    const value = urlDraft.trim();
    if (!value) return;
    setError(null);
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== "https:") {
        setError("Paste a public https link.");
        return;
      }
      const kind = /\.(mp4|webm|mov|m4v)(\?|$)/i.test(parsed.pathname) ? "video" : "image";
      onPick(kind, value);
      setUrlDraft("");
    } catch {
      setError("That doesn't look like a URL.");
    }
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
              aria-label="Remove media"
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
              {media.type === "video" ? "Video" : "Image"}
              {media.sizeBytes ? ` · ${formatBytes(media.sizeBytes)}` : ""}
            </p>
            {thumbLabel && (
              <p className="mt-1 text-[11px] font-semibold text-[var(--ui-ink)]">
                Frame mirrors: {thumbLabel}
              </p>
            )}
            <button
              type="button"
              onClick={() => fileInput.current?.click()}
              className="mt-2 rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-line)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
            >
              Replace
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
            Drop an image or video here
          </p>
          <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">
            JPG · PNG · WEBP · MP4 — up to {MAX_MEDIA_MB}MB
          </p>
          <button
            type="button"
            onClick={() => fileInput.current?.click()}
            className="mt-3 rounded-[10px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-4 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-line)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
          >
            Browse files
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
          placeholder="…or paste a public https media link"
          aria-label="Paste a media URL"
          className="min-w-[12rem] flex-1 rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] text-[var(--ui-ink)] outline-none transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-line-strong)]"
        />
        <button
          type="button"
          onClick={addUrl}
          disabled={!urlDraft.trim()}
          className="rounded-[10px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-line)] disabled:opacity-50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        >
          Add
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
          acceptFiles(e.target.files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
