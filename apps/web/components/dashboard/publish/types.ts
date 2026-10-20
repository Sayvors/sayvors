/* Shared types + platform registry for the unified Publish composer. */

export type PlatformKey =
  | "whatsapp"
  | "facebook"
  | "instagram"
  | "x"
  | "tiktok"
  | "linkedin"
  | "telegram"
  | "snapchat"
  | "google_reviews";

export type PostMethod = "post" | "story" | "reel" | "status";

export interface PublishTarget {
  id: string;
  platform: PlatformKey;
  name: string;
  handle?: string | null;
  demo?: boolean;
  /** Google Business Profile location_id when platform is google_reviews */
  locationId?: string | null;
}

export type MediaKind = "image" | "video" | null;

export interface MediaState {
  type: MediaKind;
  url: string;
  fileName?: string;
  sizeBytes?: number;
  /** The original file when the media was picked locally — needed so the
   * composer can upload it to /api/v1/media/upload for a public URL. */
  file?: File | null;
}

export interface CropState {
  key: "orig" | "1:1" | "4:5" | "16:9" | "9:16";
  zoom: number;
  x: number;
  y: number;
}

export const MAX_MEDIA_MB = 200;

export const DEFAULT_CROP: CropState = { key: "orig", zoom: 1, x: 0, y: 0 };

export interface CropSpec {
  label: string;
  hint: string;
  aspect: number | null;
}

export const CROP_SPECS: Record<Exclude<CropState["key"], "orig">, CropSpec> = {
  "1:1": { label: "Square", hint: "1:1", aspect: 1 },
  "4:5": { label: "Portrait", hint: "4:5", aspect: 4 / 5 },
  "16:9": { label: "Landscape", hint: "16:9", aspect: 16 / 9 },
  "9:16": { label: "Story", hint: "9:16", aspect: 9 / 16 },
};

export interface MethodMeta {
  label: string;
  hint: string;
}

export const METHOD_META: Record<PostMethod, MethodMeta> = {
  post: { label: "Feed post", hint: "the network's own feed" },
  story: { label: "Story", hint: "9:16 · 24h" },
  reel: { label: "Reel", hint: "9:16 video" },
  status: { label: "Status", hint: "9:16 · 24h" },
};

export const PLATFORM_METHODS: Record<PlatformKey, PostMethod[]> = {
  facebook: ["post", "story", "reel"],
  instagram: ["post", "story", "reel"],
  whatsapp: ["status"],
  google_reviews: ["post"],
  x: ["post"],
  tiktok: ["reel"],
  linkedin: ["post"],
  telegram: ["post"],
  snapchat: ["story"],
};

const PLATFORM_POST_CROP: Record<PlatformKey, CropState["key"]> = {
  facebook: "orig",
  instagram: "1:1",
  whatsapp: "orig",
  google_reviews: "orig",
  x: "16:9",
  tiktok: "9:16",
  linkedin: "16:9",
  telegram: "orig",
  snapchat: "9:16",
};

export function methodsFor(platform: PlatformKey, mediaType: MediaKind): PostMethod[] {
  const base = PLATFORM_METHODS[platform] ?? [];
  return mediaType === "video" ? base : base.filter((m) => m !== "reel");
}

export function defaultCropFor(platform: PlatformKey, method: PostMethod): CropState {
  const key = method === "post" ? PLATFORM_POST_CROP[platform] : "9:16";
  return { key, zoom: 1, x: 0, y: 0 };
}

export function cropKeyFor(targetId: string, method: PostMethod): string {
  return `${targetId}::${method}`;
}

export interface PlatformMeta {
  label: string;
  captionMax: number;
  video: boolean;
  enabled: boolean;
}

export const PLATFORM_META: Record<PlatformKey, PlatformMeta> = {
  whatsapp: { label: "WhatsApp", captionMax: 1024, video: true, enabled: true },
  facebook: { label: "Facebook", captionMax: 5000, video: true, enabled: true },
  instagram: { label: "Instagram", captionMax: 2200, video: true, enabled: true },
  google_reviews: { label: "Google Business Profile", captionMax: 1500, video: false, enabled: true },
  x: { label: "X", captionMax: 280, video: true, enabled: false },
  tiktok: { label: "TikTok", captionMax: 2200, video: true, enabled: false },
  linkedin: { label: "LinkedIn", captionMax: 3000, video: true, enabled: false },
  telegram: { label: "Telegram", captionMax: 4096, video: true, enabled: false },
  snapchat: { label: "Snapchat", captionMax: 250, video: true, enabled: false },
};

export const PLATFORM_ORDER: PlatformKey[] = [
  "instagram",
  "facebook",
  "whatsapp",
  "google_reviews",
  "linkedin",
  "tiktok",
  "x",
  "telegram",
  "snapchat",
];
