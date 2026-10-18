"use client";

import { useRef, useState } from "react";

/*
 * Visual crop frame for the unified Publish previews.
 *
 * Same interaction grammar as the Instagram CropEditor (drag to pan,
 * slider to zoom, chips to pick the ratio) but preview-only: nothing is
 * exported, the final pixels get cut at publish time. Kept separate from
 * channels/instagram/CropEditor so the dashboard page never drags that
 * module's canvas/upload contract into a surface that deliberately has
 * none yet.
 */

const BOX = 200; // on-screen editor width, css px

export const CROP_KEYS = ["orig", "1:1", "4:5", "16:9", "9:16"] as const;
export type CropKey = (typeof CROP_KEYS)[number];

export const CROP_ASPECT: Record<Exclude<CropKey, "orig">, number> = {
  "1:1": 1,
  "4:5": 4 / 5,
  "16:9": 16 / 9,
  "9:16": 9 / 16,
};

export const CROP_LABEL: Record<CropKey, string> = {
  orig: "Original",
  "1:1": "Square",
  "4:5": "Portrait",
  "16:9": "Landscape",
  "9:16": "Story",
};

export function isVideoUrl(url: string): boolean {
  if (!url) return false;
  if (url.startsWith("blob:")) {
    // blob urls carry the page's own decision — caller tracks kind there
    return false;
  }
  return /\.(mp4|webm|mov|m4v)(\?|$)/i.test(url);
}

export default function CropFrame({
  url,
  type,
  cropKey,
  zoom,
  offset,
  onCropKey,
  onZoom,
  onOffset,
}: {
  url: string | null;
  type: "image" | "video" | null;
  cropKey: CropKey;
  zoom: number;
  offset: { x: number; y: number };
  onCropKey: (k: CropKey) => void;
  onZoom: (z: number) => void;
  onOffset: (o: { x: number; y: number }) => void;
}) {
  const [naturalState, setNaturalState] = useState<{ url: string; w: number; h: number } | null>(null);
  const [errorState, setErrorState] = useState<{ url: string; text: string } | null>(null);
  const dragRef = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);

  // Derived, not effect-synced: a stale reading for another url never shows.
  const natural = naturalState && naturalState.url === url ? { w: naturalState.w, h: naturalState.h } : null;
  const error = errorState && errorState.url === url ? errorState.text : null;

  const active = cropKey !== "orig" ? cropKey : null;
  const boxH = active ? Math.round(BOX / CROP_ASPECT[active]) : BOX;
  const cover =
    active && natural ? Math.max(BOX / natural.w, boxH / natural.h) : 1;

  const clamp = (nx: number, ny: number, z: number) => {
    if (!active || !natural) return { x: nx, y: ny };
    const scale = cover * z;
    const maxX = Math.max(0, (natural.w * scale - BOX) / 2);
    const maxY = Math.max(0, (natural.h * scale - boxH) / 2);
    return {
      x: Math.min(maxX, Math.max(-maxX, nx)),
      y: Math.min(maxY, Math.max(-maxY, ny)),
    };
  };

  return (
    <div>
      {/* Ratio chips */}
      <div className="flex flex-wrap gap-1.5">
        {CROP_KEYS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => onCropKey(k)}
            aria-pressed={cropKey === k}
            title={CROP_LABEL[k]}
            className={`rounded-full border px-3 py-1 text-[11px] font-semibold transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)] ${
              cropKey === k
                ? "border-[var(--ui-ink)] bg-[var(--ui-ink)] text-[var(--ui-on-ink)]"
                : `border-[var(--ui-line)] bg-[var(--ui-surface)] text-[var(--ui-ink)] hover:bg-[var(--ui-line)]`
            }`}
          >
            {CROP_LABEL[k]}
          </button>
        ))}
      </div>

      {/* Frame */}
      <div className="mt-3 flex justify-center">
        <div
          role="application"
          aria-label="Crop frame — drag to reposition the image"
          style={{ width: BOX, height: boxH, touchAction: "none", aspectRatio: active ? String(CROP_ASPECT[active]) : undefined }}
          className={`relative flex items-center justify-center overflow-hidden rounded-[8px] bg-black ${
            active ? "cursor-grab active:cursor-grabbing" : ""
          }`}
          onPointerDown={(e) => {
            if (!active) return;
            (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
            dragRef.current = { x: e.clientX, y: e.clientY, ox: offset.x, oy: offset.y };
          }}
          onPointerMove={(e) => {
            const d = dragRef.current;
            if (!d) return;
            onOffset(clamp(d.ox + (e.clientX - d.x), d.oy + (e.clientY - d.y), zoom));
          }}
          onPointerUp={() => (dragRef.current = null)}
          onPointerCancel={() => (dragRef.current = null)}
        >
          {url && type === "image" && (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={url}
              alt=""
              draggable={false}
              onError={() =>
                setErrorState({
                  url,
                  text: "This image can't be previewed — publish will still receive it.",
                })
              }
              onLoad={(e) => {
                const el = e.currentTarget;
                setNaturalState({ url, w: el.naturalWidth, h: el.naturalHeight });
              }}
              className="pointer-events-none absolute left-1/2 top-1/2 max-w-none select-none"
              style={{
                transform: active
                  ? `translate(-50%, -50%) translate(${offset.x}px, ${offset.y}px) scale(${zoom * cover})`
                  : "translate(-50%, -50%)",
                maxHeight: active ? "none" : "100%",
                maxWidth: active ? "none" : "100%",
              }}
            />
          )}
          {url && type === "video" && (
            <video
              src={url}
              muted
              playsInline
              controls={false}
              className={`pointer-events-none ${active ? "absolute left-1/2 top-1/2 h-auto w-full max-w-none" : "max-h-full max-w-full"}`}
              style={
                active
                  ? { transform: `translate(-50%, -50%) translate(${offset.x}px, ${offset.y}px) scale(${zoom * cover})` }
                  : undefined
              }
            />
          )}
          {!url && (
            <p className="px-4 text-center text-[12px] font-semibold text-white/50">
              Add media to crop it here
            </p>
          )}
          {error && (
            <p role="alert" className="absolute inset-x-3 z-10 rounded-[8px] bg-white/95 p-2 text-center text-[11px] font-semibold text-red-600">
              {error}
            </p>
          )}
        </div>
      </div>

      {/* Zoom — only meaningful when an explicit ratio is active */}
      {active && (
        <div className="mt-3 flex items-center gap-3">
          <label htmlFor="publish-crop-zoom" className="text-[12px] font-semibold text-[var(--ui-ink-2)]">
            Zoom
          </label>
          <input
            id="publish-crop-zoom"
            type="range"
            min={1}
            max={3}
            step={0.01}
            value={zoom}
            onChange={(e) => {
              const z = Number(e.target.value);
              onZoom(z);
              onOffset(clamp(offset.x, offset.y, z));
            }}
            className="h-1.5 flex-1 accent-[var(--ui-ink)]"
          />
        </div>
      )}
      <p className="mt-2 text-center text-[10px] font-semibold uppercase tracking-widest text-[var(--ui-ink-2)]">
        Preview crop — applied for real when this post publishes
      </p>
    </div>
  );
}
