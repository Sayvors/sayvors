/**
 * Bakes a crop frame into pixels.
 *
 * The crop editor is a CSS transform: it scales the image to cover a 200px
 * box and pans it. Nothing was ever rasterised, so every publish shipped the
 * full original — a merchant who framed a 1:1 avatar for a profile picture
 * got Google's own centre-crop instead of the framing they saw.
 *
 * This module reproduces the editor's cover-scale + pan maths on a canvas,
 * so the file that reaches the provider is the crop that was configured.
 * It is deliberately DOM-only and free of React: callers pass a URL or a
 * File and get a File back.
 */

export type CropShape = {
  key: "orig" | "1:1" | "4:5" | "16:9" | "9:16";
  zoom: number;
  x: number;
  y: number;
};

/** The crop editor's on-screen box width, in CSS pixels. */
export const CROP_EDITOR_BOX = 200;

/** Longest edge of an exported crop. Providers re-encode anyway; this keeps
 *  a 6000px original from producing a 20MB upload after a 2x zoom. */
const MAX_EXPORT_EDGE = 2048;

const ASPECT: Record<Exclude<CropShape["key"], "orig">, number> = {
  "1:1": 1,
  "4:5": 4 / 5,
  "16:9": 16 / 9,
  "9:16": 9 / 16,
};

type Loaded = { bitmap: ImageBitmap; mime: string };

export type CropRect = {
  /** Left edge in source-bitmap pixels. */
  x: number;
  /** Top edge in source-bitmap pixels. */
  y: number;
  w: number;
  h: number;
};

/**
 * The part of a `width` x `height` source image that the crop frame shows.
 *
 * Pure on purpose: the canvas path and its tests share one definition of the
 * editor's framing, so the shipped pixels cannot drift from the preview.
 *
 * @throws when the stored offset puts the frame entirely outside the image.
 */
export function cropSourceRect(
  width: number,
  height: number,
  crop: CropShape,
): CropRect | null {
  if (crop.key === "orig") return null;

  const aspect = ASPECT[crop.key];
  const boxW = CROP_EDITOR_BOX;
  const boxH = Math.round(boxW / aspect);

  // Mirrors CropFrame: cover-scale the image into the box, then apply the
  // stored pan offset (which is in editor pixels) and the zoom.
  const cover = Math.max(boxW / width, boxH / height);
  const scale = Math.max(1e-6, cover * Math.max(0.01, crop.zoom));
  const left = (boxW - width * scale) / 2 + crop.x;
  const top = (boxH - height * scale) / 2 + crop.y;

  // The visible source rectangle. Clamped so drawImage can never read
  // outside the bitmap when an offset sits at the edge.
  const x = Math.max(0, -left / scale);
  const y = Math.max(0, -top / scale);
  const w = Math.min(width - x, boxW / scale);
  const h = Math.min(height - y, boxH / scale);
  if (w <= 0 || h <= 0) {
    throw new Error("the crop landed outside the image");
  }
  return { x, y, w, h };
}

async function loadImage(file: File | null, url: string): Promise<Loaded> {
  let blob: Blob;
  if (file) {
    blob = file;
  } else {
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`the image could not be read (${res.status})`);
    }
    blob = await res.blob();
  }
  return { bitmap: await createImageBitmap(blob), mime: blob.type };
}

/**
 * The cropped file for a format, or ``null`` when there is nothing to do.
 *
 * ``null`` means "publish the original": an ``orig`` crop, or a video, which
 * a canvas cannot cut without dropping its audio track.
 */
export async function exportCroppedImage(
  source: { url: string; file?: File | null; type?: string | null },
  crop: CropShape,
): Promise<File | null> {
  if (crop.key === "orig" || source.type === "video") return null;

  const { bitmap, mime } = await loadImage(source.file ?? null, source.url);
  try {
    const rect = cropSourceRect(bitmap.width, bitmap.height, crop);
    if (!rect) return null;
    const { x: srcX, y: srcY, w: srcW, h: srcH } = rect;

    const shrink = Math.min(1, MAX_EXPORT_EDGE / Math.max(srcW, srcH));
    const outW = Math.max(1, Math.round(srcW * shrink));
    const outH = Math.max(1, Math.round(srcH * shrink));

    const canvas = document.createElement("canvas");
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("this browser cannot draw the crop");
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bitmap, srcX, srcY, srcW, srcH, 0, 0, outW, outH);

    // PNG keeps transparency (logos); everything else is a photo, and JPEG
    // keeps the upload small.
    const isPng = mime === "image/png";
    const outMime = isPng ? "image/png" : "image/jpeg";
    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, outMime, 0.92),
    );
    if (!blob) throw new Error("the browser could not encode the crop");

    const base = (source.file?.name ?? "image").replace(/\.[^.]+$/, "");
    return new File([blob], `${base}-crop.${isPng ? "png" : "jpg"}`, {
      type: outMime,
    });
  } finally {
    bitmap.close();
  }
}

/** A stable key for a crop, so one publish uploads each variant once. */
export function cropSignature(crop: CropShape): string {
  return [crop.key, crop.zoom, Math.round(crop.x), Math.round(crop.y)].join("|");
}
