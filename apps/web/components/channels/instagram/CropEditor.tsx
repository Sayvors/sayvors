"use client";

import { useRef, useState } from "react";
import { INK, INK2 } from "./ui";
import { useI18n } from "@/lib/i18n/I18nProvider";
import type { Dict } from "@/lib/i18n/en";

/*
 * Instagram-style crop: pick a supported aspect ratio, drag to reposition,
 * zoom, done — the visible frame becomes the uploaded image. The canvas
 * crop happens client-side at Instagram's own recommended resolutions, so
 * what the tenant frames is exactly what the feed shows (Meta otherwise
 * crops carousel images itself, based on the FIRST image, default 1:1).
 */

export type CropRatio = {
  key: "1:1" | "4:5" | "1.91:1" | "9:16" | "orig";
  label: string;
  hint: string;
  /** aspect = width / height; null = keep the original untouched */
  aspect: number | null;
  /** pixel dimensions of the exported canvas (Instagram's recommended) */
  out: [number, number] | null;
};

export const CROP_RATIOS: CropRatio[] = [
  { key: "1:1", label: "Square", hint: "1:1", aspect: 1, out: [1080, 1080] },
  { key: "4:5", label: "Portrait", hint: "4:5", aspect: 4 / 5, out: [1080, 1350] },
  { key: "1.91:1", label: "Landscape", hint: "1.91:1", aspect: 1.91, out: [1080, 566] },
  { key: "orig", label: "Original", hint: "as-is", aspect: null, out: null },
];

/** The story ratio lives outside the feed chips — stories are always 9:16. */
export const STORY_RATIO: CropRatio = {
  key: "9:16", label: "Story", hint: "9:16", aspect: 9 / 16, out: [1080, 1920],
};

function loadImage(src: string, unreadable: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(unreadable));
    img.src = src;
  });
}

/*
 * One stable blob URL per file, kept alive for the whole session. React's
 * dev StrictMode double-runs effects, so an unmount cleanup that revokes
 * the URL kills the remount's <img> mid-load — every PNG would "fail" to
 * read. The WeakMap lets entries go when the File itself is collected.
 */
const blobUrlCache = new WeakMap<File, string>();

function fileUrl(file: File): string {
  let url = blobUrlCache.get(file);
  if (!url) {
    url = URL.createObjectURL(file);
    blobUrlCache.set(file, url);
  }
  return url;
}

/** Translated copy `centerCropBlob` needs — the caller owns the locale. */
export type CropCopy = {
  unreadable: string;
  noCanvas: string;
  cropFailed: string;
};

const EN_COPY: CropCopy = {
  unreadable: "Could not read this image.",
  noCanvas: "Canvas unavailable in this browser.",
  cropFailed: "Crop failed.",
};

/** Center-crop any image to a ratio — used for the automatic 9:16 story
 * variant, so the tenant doesn't crop the same photo twice. */
export async function centerCropBlob(
  file: File,
  ratio: CropRatio,
  copy: CropCopy = EN_COPY,
): Promise<Blob> {
  const url = URL.createObjectURL(file);
  try {
    const img = await loadImage(url, copy.unreadable);
    const canvas = document.createElement("canvas");
    canvas.width = ratio.out![0];
    canvas.height = ratio.out![1];
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error(copy.noCanvas);
    const targetAspect = canvas.width / canvas.height;
    const srcAspect = img.naturalWidth / img.naturalHeight;
    let sw: number;
    let sh: number;
    if (srcAspect > targetAspect) {
      sh = img.naturalHeight;
      sw = sh * targetAspect;
    } else {
      sw = img.naturalWidth;
      sh = sw / targetAspect;
    }
    ctx.drawImage(
      img,
      (img.naturalWidth - sw) / 2,
      (img.naturalHeight - sh) / 2,
      sw, sh,
      0, 0, canvas.width, canvas.height,
    );
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error(copy.cropFailed))),
        "image/jpeg",
        0.92,
      ),
    );
  } finally {
    URL.revokeObjectURL(url);
  }
}

export type CropDict = Dict["channelHub"]["instagram"]["cropper"];

/** Ratio labels live in the dictionary so Arabic shows MSA, not "Square". */
export function ratioLabel(r: CropRatio, c: CropDict): string {
  switch (r.key) {
    case "1:1":
      return c.ratios.square;
    case "4:5":
      return c.ratios.portrait;
    case "1.91:1":
      return c.ratios.landscape;
    case "9:16":
      return c.ratios.story;
    case "orig":
      return c.ratios.original;
  }
}

export function ratioHint(r: CropRatio, c: CropDict): string {
  return r.key === "orig" ? c.ratios.asIs : r.hint;
}

const BOX = 288; // editor frame on screen, css px

export default function CropEditor({
  file,
  ratio,
  onRatio,
  index,
  total,
  working = false,
  onCancel,
  onDone,
}: {
  file: File;
  ratio: CropRatio;
  onRatio: (r: CropRatio) => void;
  index: number;
  total: number;
  /** true while the cropped blob uploads — Done is disabled so a double
   * click can't queue the same image twice */
  working?: boolean;
  onCancel: () => void;
  onDone: (blob: Blob) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const dragRef = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const { t } = useI18n();
  const c = t.channelHub.instagram.cropper;

  // Derived from the file; never revoked mid-session (see fileUrl above).
  const imgUrl = fileUrl(file);

  const boxH = ratio.aspect ? Math.round(BOX / ratio.aspect) : BOX;
  const activeRatio = ratio.aspect ? ratio : null;
  const cover = activeRatio && natural
    ? Math.max(BOX / natural.w, boxH / natural.h)
    : 1;

  const clampOffset = (nx: number, ny: number, z: number) => {
    if (!activeRatio || !natural) return { x: nx, y: ny };
    const scale = cover * z;
    const maxX = Math.max(0, (natural.w * scale - BOX) / 2);
    const maxY = Math.max(0, (natural.h * scale - boxH) / 2);
    return {
      x: Math.min(maxX, Math.max(-maxX, nx)),
      y: Math.min(maxY, Math.max(-maxY, ny)),
    };
  };

  const buildBlob = async (): Promise<Blob> => {
    const img = imgRef.current;
    if (!img) throw new Error(c.errors.stillLoading);
    if (!activeRatio || !ratio.out) return file; // original: untouched
    const canvas = document.createElement("canvas");
    canvas.width = ratio.out[0];
    canvas.height = ratio.out[1];
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error(c.errors.noCanvas);
    const coverNow = Math.max(BOX / img.naturalWidth, boxH / img.naturalHeight);
    const scale = coverNow * zoom;
    // The frame's top-left in natural image pixels — the same math that
    // places the <img> on screen, inverted.
    const sx = (img.naturalWidth - BOX / scale) / 2 - offset.x / scale;
    const sy = (img.naturalHeight - boxH / scale) / 2 - offset.y / scale;
    ctx.drawImage(
      img, sx, sy, BOX / scale, boxH / scale,
      0, 0, canvas.width, canvas.height,
    );
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(
        (b) => (b ? resolve(b) : reject(new Error(c.errors.cropFailed))),
        "image/jpeg",
        0.92,
      ),
    );
  };

  return (
    <div
      className="rounded-[16px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-4"
      onDragOver={(e) => e.preventDefault()}
    >
      <div className="flex items-baseline justify-between">
        <p className={`text-[13px] font-semibold ${INK}`}>
          {c.title}{" "}
          {total > 1
            ? c.counter
                .replaceAll("{i}", String(index + 1))
                .replaceAll("{total}", String(total))
            : ""}
        </p>
        <p className={`text-[12px] ${INK2}`}>{ratioLabel(ratio, c)} · {ratioHint(ratio, c)}</p>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {CROP_RATIOS.map((r) => (
          <button
            key={r.key}
            type="button"
            onClick={() => onRatio(r)}
            className={`rounded-full border px-3 py-1 text-[12px] font-semibold ${
              ratio.key === r.key
                ? "border-[var(--ui-ink)] bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                : `border-[var(--ui-line)] bg-[var(--ui-surface)] ${INK} hover:bg-[var(--ui-line)]`
            }`}
          >
            {ratioLabel(r, c)}
          </button>
        ))}
      </div>

      <div className="mt-3 flex justify-center">
        <div
          role="application"
          aria-label={c.frameAria}
          style={{ width: BOX, height: boxH, touchAction: "none" }}
          className="relative flex cursor-grab items-center justify-center overflow-hidden rounded-[8px] bg-black active:cursor-grabbing"
          onPointerDown={(e) => {
            (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
            dragRef.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
          }}
          onPointerMove={(e) => {
            const d = dragRef.current;
            if (!d) return;
            const next = clampOffset(
              d.ox + (e.clientX - d.x), d.oy + (e.clientY - d.y), zoom,
            );
            setOffset(next);
          }}
          onPointerUp={() => {
            dragRef.current = null;
          }}
          onPointerCancel={() => {
            dragRef.current = null;
          }}
        >
          {imgUrl && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              ref={(el) => {
                imgRef.current = el;
                if (el && el.naturalWidth && (!natural || natural.w !== el.naturalWidth)) {
                  setNatural({ w: el.naturalWidth, h: el.naturalHeight });
                }
              }}
              src={imgUrl}
              alt={c.sourceAlt}
              draggable={false}
              onError={() =>
                setLoadError(c.errors.badFormat)
              }
              className="pointer-events-none absolute left-1/2 top-1/2 max-w-none select-none"
              style={{
                transform: activeRatio
                  ? `translate(-50%, -50%) translate(${offset.x}px, ${offset.y}px) scale(${zoom * cover})`
                  : "translate(-50%, -50%)",
                maxHeight: activeRatio ? "none" : "100%",
                maxWidth: activeRatio ? "none" : "100%",
              }}
            />
          )}
          {loadError && (
            <p
              role="alert"
              className="absolute inset-x-3 z-10 rounded-[8px] bg-white/95 p-2 text-center text-[12px] font-semibold text-red-600"
            >
              {loadError}
            </p>
          )}
        </div>
      </div>

      {activeRatio && (
        <div className="mt-3 flex items-center gap-3">
          <span className={`text-[12px] font-semibold ${INK2}`}>{c.zoom}</span>
          <input
            type="range"
            min={1}
            max={3}
            step={0.01}
            value={zoom}
            aria-label={c.zoom}
            onChange={(e) => {
              const z = Number(e.target.value);
              setZoom(z);
              setOffset((o) => clampOffset(o.x, o.y, z));
            }}
            className="flex-1 accent-black"
          />
        </div>
      )}

      <div className="mt-4 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-ink)]"
        >
          {c.cancel}
        </button>
        <button
          type="button"
          disabled={working}
          onClick={() => {
            void buildBlob()
              .then(onDone)
              .catch((e: unknown) => {
                setLoadError(
                  e instanceof Error ? e.message : c.errors.processFailed,
                );
              });
          }}
          className="rounded-[12px] bg-[var(--ui-ink)] px-4 py-2 text-[12px] font-semibold text-[var(--ui-on-ink)] disabled:opacity-50"
        >
          {working ? c.uploading : c.done}
        </button>
      </div>
    </div>
  );
}
