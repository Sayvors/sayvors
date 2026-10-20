"use client";

import { CROP_ASPECT } from "./CropFrame";
import CroppedMedia from "./CroppedMedia";
import type { CropState, MediaState } from "./types";

/*
 * FormatThumb — the small crop preview that rides on each format pill.
 *
 * The pill label alone ("Story", "Event", "Profile picture") says which
 * format is on; the thumbnail says what that format will actually look
 * like with the crop the tenant has set. It renders through the same
 * CroppedMedia the live preview uses, at the format's own aspect ratio,
 * so the thumbnail and the preview can never disagree.
 *
 * "orig" has no fixed ratio, so the thumb falls back to a square — the
 * source image's own shape is what gets published in that case.
 */

const THUMB_H = 26; // css px, matches the pill's line height
const THUMB_MAX_W = 46; // keeps a 16:9 thumb from stretching the pill

export default function FormatThumb({
  media,
  crop,
  className = "",
}: {
  media: MediaState | null;
  crop: CropState;
  className?: string;
}) {
  const aspect = crop.key === "orig" ? 1 : CROP_ASPECT[crop.key];
  const w = Math.min(THUMB_MAX_W, Math.max(12, Math.round(THUMB_H * aspect)));

  return (
    <span
      aria-hidden
      className={`relative block shrink-0 overflow-hidden rounded-[5px] bg-black/15 ${className}`}
      style={{ width: w, height: THUMB_H }}
    >
      {media?.type ? (
        <CroppedMedia
          media={media}
          cropKey={crop.key}
          zoom={crop.zoom}
          offset={{ x: crop.x, y: crop.y }}
          boxW={w}
          aspect={aspect}
        />
      ) : null}
    </span>
  );
}
