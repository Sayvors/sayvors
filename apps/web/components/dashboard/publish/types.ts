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

/**
 * A publish "format" — one surface a post lands on.
 *
 * Meta: post / story / reel / status.
 * Google Business Profile: update / event / offer (the three post types
 * Google itself offers — an announcement, a dated event, a promotion).
 * Profile surfaces: profile / banner — changing the avatar or cover image
 * of an account rather than publishing into its feed.
 */
export type PostMethod =
  | "post"
  | "story"
  | "reel"
  | "status"
  | "update"
  | "event"
  | "offer"
  | "profile"
  | "banner";

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
  /** The storage key of the media once it lives in our own storage.
   * Providers that upload bytes rather than fetch a URL (WhatsApp's
   * profile picture) can only work on media we hold, so the key is
   * sent along with the publish request. */
  key?: string | null;
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
  update: { label: "Update", hint: "announcement on your business profile" },
  event: { label: "Event", hint: "dated event with a schedule" },
  offer: { label: "Promotion", hint: "offer, discount or coupon" },
  profile: { label: "Profile picture", hint: "1:1 · your avatar" },
  banner: { label: "Banner", hint: "16:9 · cover image" },
};

/**
 * Which formats each platform can actually deliver.
 *
 * This is the fail-closed list: a format that is not here is never
 * offered, so the tenant cannot queue a job the provider would reject.
 * Instagram has no profile/banner because Meta's IG User node is
 * read-only for those fields ("Updating: not supported").
 */
export const PLATFORM_METHODS: Record<PlatformKey, PostMethod[]> = {
  facebook: ["post", "story", "reel", "profile", "banner"],
  instagram: ["post", "story", "reel"],
  whatsapp: ["status", "profile"],
  google_reviews: ["update", "event", "offer", "profile", "banner"],
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

/**
 * Formats that publish into a feed.
 *
 * The account surfaces (profile / banner) REPLACE the tenant's avatar
 * and cover image. They are deliberately excluded from any bulk
 * selection: replacing someone's identity image has to be a deliberate,
 * individual choice, never a side effect of "select all".
 */
const FEED_METHODS = new Set<PostMethod>([
  "post",
  "story",
  "reel",
  "status",
  "update",
  "event",
  "offer",
]);

export function isFeedMethod(method: PostMethod): boolean {
  return FEED_METHODS.has(method);
}

export function methodsFor(platform: PlatformKey, mediaType: MediaKind): PostMethod[] {
  const base = PLATFORM_METHODS[platform] ?? [];
  if (mediaType === "video") {
    // An avatar or a cover image is still an image — offering them for a
    // video would queue a job the provider must reject.
    return base.filter((m) => m !== "profile" && m !== "banner");
  }
  // A reel needs a video to be a reel.
  return base.filter((m) => m !== "reel");
}

export function defaultCropFor(platform: PlatformKey, method: PostMethod): CropState {
  // Profile surfaces have a shape the platform decides, so they get a
  // fixed ratio rather than the platform's feed crop.
  if (method === "profile") return { key: "1:1", zoom: 1, x: 0, y: 0 };
  if (method === "banner") return { key: "16:9", zoom: 1, x: 0, y: 0 };
  // Meta story/reel/status formats are 9:16; every other method uses the
  // platform's post crop (Google "Update"/"Event"/"Promotion" all use the
  // same landscape frame).
  const storyLike = method === "story" || method === "reel" || method === "status";
  return { key: storyLike ? "9:16" : PLATFORM_POST_CROP[platform], zoom: 1, x: 0, y: 0 };
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
