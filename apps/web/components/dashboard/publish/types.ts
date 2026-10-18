/*
 * Shared types + platform registry for the unified Publish composer.
 *
 * UI-first: every payload here is local state until the publish endpoint
 * lands. The registry is the extension point — a new network is a row in
 * PLATFORM_META plus its own preview variant, never edits inside the
 * composer body.
 */

export type PlatformKey =
  | "whatsapp"
  | "facebook"
  | "instagram"
  | "x"
  | "tiktok"
  | "linkedin"
  | "telegram"
  | "snapchat";

/** Media sink cap — one handling truth for the whole composer. */
export const MAX_MEDIA_MB = 200;

export interface PublishTarget {
  /** Stable id — the Meta asset (or demo) id, unique across allproviders. */
  id: string;
  platform: PlatformKey;
  /** Display name of the account/Page/number. */
  name: string;
  /** Optional handle or phone shown under the name. */
  handle?: string | null;
  /** True when the composer generated a demo row (no live connection). */
  demo?: boolean;
}

export type MediaKind = "image" | "video" | null;

export interface MediaState {
  type: MediaKind;
  /** Stable local url for preview (blob or pasted https). */
  url: string;
  fileName?: string;
  sizeBytes?: number;
}

export interface CropState {
  key: "orig" | "1:1" | "4:5" | "16:9" | "9:16";
  zoom: number;
  x: number;
  y: number;
}

export const DEFAULT_CROP: CropState = { key: "orig", zoom: 1, x: 0, y: 0 };

export interface CropSpec {
  label: string;
  hint: string;
  aspect: number | null;
}

/** The per-preview crop presets. "orig" keeps the untouched frame. */
export const CROP_SPECS: Record<Exclude<CropState["key"], "orig">, CropSpec> = {
  "1:1": { label: "Square", hint: "1:1", aspect: 1 },
  "4:5": { label: "Portrait", hint: "4:5", aspect: 4 / 5 },
  "16:9": { label: "Landscape", hint: "16:9", aspect: 16 / 9 },
  "9:16": { label: "Story", hint: "9:16", aspect: 9 / 16 },
};

export interface PlatformMeta {
  label: string;
  /** Aspect the platform prefers for a single image, orig = native. */
  defaultCrop: CropState["key"];
  /** Character budget shown under the caption/description. */
  captionMax: number;
  /** Whether this platform accepts video posts. */
  video: boolean;
  /** Whether the composer offers it at all (false until a hub exists). */
  enabled: boolean;
}

export const PLATFORM_META: Record<PlatformKey, PlatformMeta> = {
  whatsapp: { label: "WhatsApp", defaultCrop: "orig", captionMax: 1024, video: true, enabled: true },
  facebook: { label: "Facebook", defaultCrop: "orig", captionMax: 5000, video: true, enabled: true },
  instagram: { label: "Instagram", defaultCrop: "1:1", captionMax: 2200, video: true, enabled: true },
  x: { label: "X", defaultCrop: "16:9", captionMax: 280, video: true, enabled: false },
  tiktok: { label: "TikTok", defaultCrop: "9:16", captionMax: 2200, video: true, enabled: false },
  linkedin: { label: "LinkedIn", defaultCrop: "16:9", captionMax: 3000, video: true, enabled: false },
  telegram: { label: "Telegram", defaultCrop: "orig", captionMax: 4096, video: true, enabled: false },
  snapchat: { label: "Snapchat", defaultCrop: "9:16", captionMax: 250, video: true, enabled: false },
};

export const PLATFORM_ORDER: PlatformKey[] = [
  "instagram",
  "facebook",
  "whatsapp",
  "linkedin",
  "tiktok",
  "x",
  "telegram",
  "snapchat",
];

/* ── Formats: what shape this post takes on each network ──────────── */

export type PostMethod = "post" | "story" | "reel" | "status";

export const METHOD_META: Record<PostMethod, { label: string; hint: string }> = {
  post: { label: "Post", hint: "Feed" },
  story: { label: "Story", hint: "24h" },
  reel: { label: "Reel", hint: "Video" },
  status: { label: "Status", hint: "24h" },
};

export const PLATFORM_METHODS: Record<PlatformKey, PostMethod[]> = {
  instagram: ["post", "story", "reel"],
  facebook: ["post", "story", "reel"],
  whatsapp: ["status"],
  linkedin: ["post"],
  tiktok: ["post"],
  x: ["post"],
  telegram: ["post"],
  snapchat: ["post"],
};

/** Formats a network offers for the current media type — "reel" needs video. */
export function methodsFor(platform: PlatformKey, mediaType: MediaKind): PostMethod[] {
  return PLATFORM_METHODS[platform].filter((m) => m !== "reel" || mediaType === "video");
}

/** Crop a format starts from: vertical formats go 9:16, feed uses the
 *  network's own preferred aspect. */
export function defaultCropFor(platform: PlatformKey, method: PostMethod): CropState {
  const key: CropState["key"] = method === "post" ? PLATFORM_META[platform].defaultCrop : "9:16";
  return { key, zoom: 1, x: 0, y: 0 };
}
