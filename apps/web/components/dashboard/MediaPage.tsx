/**
 * Media item types shared by the surface feed.
 *
 * The standalone media library was folded into the Publish composer (step 1),
 * so this module now exports only the shared types/helpers — no component.
 */

export interface MediaItem {
  id: string;
  type: "PHOTO" | "VIDEO";
  source: "OWN" | "CUSTOMER";
  category: string;
  thumbnailUrl?: string;
  sourceUrl?: string;
  views: number;
  attribution?: string;
  createdAt: string;
  isProfile?: boolean;
  isCover?: boolean;
  status?: "DRAFT" | "SCHEDULED" | "PUBLISHED" | "FAILED";
  scheduledAt?: string;
  error?: string;
  method?: string;
}

export function normalizeMedia(raw: unknown): MediaItem[] {
  const list = Array.isArray(raw) ? raw : (raw as { media?: unknown[] }).media;
  if (!Array.isArray(list)) return [];
  return (list as Record<string, unknown>[]).map((m, i) => {
    const url = typeof m.image_url === "string" ? m.image_url : undefined;
    const statusRaw = typeof m.status === "string" ? m.status : "draft";
    const status =
      statusRaw === "scheduled" ? "SCHEDULED" :
      statusRaw === "published" ? "PUBLISHED" :
      statusRaw === "failed" ? "FAILED" : "DRAFT";
    return {
      id: String(m.id ?? `m_${i}`),
      type: m.type === "VIDEO" ? "VIDEO" : "PHOTO",
      source: "OWN",
      category: String(m.category ?? "EXTERIOR"),
      thumbnailUrl: url,
      sourceUrl: url,
      views: 0,
      createdAt: String(m.created_at ?? m.createdAt ?? new Date().toISOString().slice(0, 10)).slice(0, 10),
      isProfile: m.is_profile === true,
      isCover: m.is_cover === true,
      status,
      scheduledAt: m.scheduled_on ? String(m.scheduled_on) : undefined,
      error: typeof m.error === "string" ? m.error : undefined,
      method: typeof m.publish_method === "string" ? m.publish_method : undefined,
    };
  });
}


