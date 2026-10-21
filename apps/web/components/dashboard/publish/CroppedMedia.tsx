"use client";

import { useState } from "react";
import { CROP_BOX } from "./CropFrame";
import type { CropState, MediaState } from "./types";

/*
 * CroppedMedia — renders media inside a box so it matches the crop frame
 * EXACTLY. It tracks the media's natural dimensions, computes the same
 * cover scale the crop frame uses, and applies the same pan offset scaled
 * to this box's size. This is what makes every crop surface — the big
 * live preview, the format pill thumbnail, the modal preview — an honest
 * mirror of the crop editor.
 *
 * The stored pan offset is in editor pixels, so it is scaled by
 * (boxW / CROP_BOX) here. Using anything else makes the preview pan by a
 * different amount than the editor does, which is exactly the kind of
 * drift that makes a tenant ship a crop they never saw.
 */
export default function CroppedMedia({
  media,
  cropKey,
  zoom,
  offset,
  boxW,
  aspect,
  className = "",
}: {
  media: MediaState;
  cropKey: CropState["key"];
  zoom: number;
  offset: { x: number; y: number };
  boxW: number;
  aspect: number;
  className?: string;
}) {
  const boxH = aspect > 0 ? Math.round(boxW / aspect) : boxW;
  const [naturalState, setNaturalState] = useState<{ url: string; w: number; h: number } | null>(null);

  const active = cropKey !== "orig" ? cropKey : null;
  const url = media?.url ?? "";
  const natural = naturalState && naturalState.url === url ? { w: naturalState.w, h: naturalState.h } : null;

  if (!media.type) return null;

  if (media.type === "video") {
    if (!active) {
      return (
        <video
          src={media.url}
          muted
          loop
          autoPlay
          playsInline
          className={`h-full w-full object-cover ${className}`}
        />
      );
    }
    // Videos: apply the same transform as images using videoWidth/Height
    const cover = natural ? Math.max(boxW / natural.w, boxH / natural.h) : 1;
    const scale = zoom * cover;
    const s = boxW / CROP_BOX;
    return (
      <video
        src={media.url}
        muted
        loop
        autoPlay
        playsInline
        className={`absolute left-1/2 top-1/2 max-w-none select-none ${className}`}
        style={{
          transform: `translate(-50%, -50%) translate(${offset.x * s}px, ${offset.y * s}px) scale(${scale})`,
        }}
        onLoadedMetadata={(e) => {
          const v = e.currentTarget;
          if (v.videoWidth && v.videoHeight) {
            setNaturalState({ url, w: v.videoWidth, h: v.videoHeight });
          }
        }}
      />
    );
  }

  if (!active) {
    return (
      /* eslint-disable-next-line @next/next/no-img-element */
      <img
        src={media.url}
        alt=""
        className={`h-full w-full object-cover ${className}`}
        onLoad={(e) => {
          const img = e.currentTarget;
          setNaturalState({ url, w: img.naturalWidth, h: img.naturalHeight });
        }}
      />
    );
  }

  if (!natural) {
    return (
      /* eslint-disable-next-line @next/next/no-img-element */
      <img
        src={media.url}
        alt=""
        className={`h-full w-full object-cover ${className}`}
        onLoad={(e) => {
          const img = e.currentTarget;
          setNaturalState({ url, w: img.naturalWidth, h: img.naturalHeight });
        }}
      />
    );
  }

  const cover = Math.max(boxW / natural.w, boxH / natural.h);
  const scale = zoom * cover;
  const s = boxW / CROP_BOX;
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src={media.url}
      alt=""
      className={`absolute left-1/2 top-1/2 max-w-none select-none ${className}`}
      style={{
        transform: `translate(-50%, -50%) translate(${offset.x * s}px, ${offset.y * s}px) scale(${scale})`,
      }}
      onLoad={(e) => {
        const img = e.currentTarget;
        setNaturalState({ url, w: img.naturalWidth, h: img.naturalHeight });
      }}
    />
  );
}
