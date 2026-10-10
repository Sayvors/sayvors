"use client";

import { apiFetch } from "./api-rag";

export type MetaProvider = "whatsapp" | "facebook" | "instagram";

export interface MetaConnection {
  id: string;
  provider: MetaProvider;
  connection_type: string;
  meta_business_id: string | null;
  scopes: string[];
  status: string;
  last_validated_at: string | null;
  last_successful_api_call_at: string | null;
  last_webhook_received_at: string | null;
  created_at: string;
}

export interface MetaAsset {
  id: string;
  provider: MetaProvider;
  asset_type: string;
  external_asset_id: string;
  parent_asset_id: string | null;
  name: string | null;
  username: string | null;
  phone: string | null;
  active: boolean;
  status: string;
}

export interface MetaConnectEntry {
  provider: string;
  auth_url?: string | null;
  fb_app_id?: string | null;
  /** Embedded Signup config for the standard (new number) flow. */
  fb_config_id?: string | null;
  /**
   * Embedded Signup config for the Coexistence flow ("Connect existing",
   * the customer keeps their number + WhatsApp Business App). Meta scopes
   * this to a separate Builder configuration, so the two flows cannot
   * share one config_id. Server falls back to fb_config_id when unset.
   */
  fb_coexistence_config_id?: string | null;
  graph_api_version?: string | null;
  solution_id?: string | null;
  state: string;
  note?: string | null;
}

export const fetchMetaConnections = (): Promise<{ connections: MetaConnection[] }> =>
  apiFetch("/api/v1/meta/connections");

export const startMetaConnect = (provider: MetaProvider): Promise<MetaConnectEntry> =>
  apiFetch(`/api/v1/meta/${provider}/connect`, { method: "POST" });

export const postWhatsAppSession = (body: {
  state: string;
  code?: string | null;
  waba_id?: string | null;
  phone_number_id?: string | null;
  business_id?: string | null;
  /** 6-digit two-step PIN. Without it Meta refuses to register the number. */
  pin?: string | null;
  /** Onboarding mode: 'standard' (new number) or 'coexistence' (existing Business app number) */
  mode?: "standard" | "coexistence" | null;
}): Promise<{
  connected: boolean;
  assets_found: number;
  registered?: string[];
  registration_failed?: { asset_id: string; asset_type: string; status: number }[];
  /** The number connected but cannot send until a PIN is supplied. */
  needs_pin?: boolean;
}> =>
  apiFetch("/api/v1/meta/whatsapp/session", {
    method: "POST",
    body: JSON.stringify(body),
  });

/** Retry registration for a number Meta rejected (allowed for 14 days). */
export const registerWhatsAppNumber = (
  phoneNumberId: string,
  pin: string
): Promise<{ registered: boolean; phone_number_id: string }> =>
  apiFetch(`/api/v1/meta/whatsapp/${encodeURIComponent(phoneNumberId)}/register`, {
    method: "POST",
    body: JSON.stringify({ pin }),
  });

export const fetchMetaAssets = (
  provider: MetaProvider
): Promise<{ assets: MetaAsset[] }> => apiFetch(`/api/v1/meta/${provider}/assets`);

export const selectMetaAssets = (
  provider: MetaProvider,
  asset_ids: string[]
): Promise<{ assets: MetaAsset[] }> =>
  apiFetch(`/api/v1/meta/${provider}/assets/select`, {
    method: "POST",
    body: JSON.stringify({ asset_ids }),
  });

export const discoverInstagram = (): Promise<{ assets: MetaAsset[] }> =>
  apiFetch("/api/v1/meta/instagram/discover", { method: "POST" });

export const validateMeta = (provider: MetaProvider) =>
  apiFetch(`/api/v1/meta/${provider}/validate`, { method: "POST" });

/**
 * Instagram business profile — READ ONLY.
 *
 * Meta's IG User reference states updating a profile is not supported, so
 * there is deliberately no update call here. Everything on this page is
 * rendered as a value, never as an editable field.
 */
export interface InstagramProfile {
  username: string | null;
  name: string | null;
  biography: string | null;
  website: string | null;
  profile_picture_url: string | null;
  followers_count: number;
  follows_count: number;
  media_count: number;
  // Meta does not expose account_type on the IG User node, so Sayvors reports
  // what it stores at connect time instead.
  status: string | null;
  eligibility: string | null;
  parent_page_id: string | null;
  parent_page_name: string | null;
  synced_at: string | null;
  stale: boolean;
}

export const fetchInstagramProfile = (
  igId: string,
  opts?: { refresh?: boolean }
): Promise<InstagramProfile> =>
  apiFetch(
    `/api/v1/meta/instagram/${encodeURIComponent(igId)}/profile${
      opts?.refresh ? "?refresh=true" : ""
    }`
  );

/**
 * Instagram audience.
 *
 * There is no follower list here and there cannot be: Meta does not expose
 * follower/following lists. What this returns is who actually engaged - people
 * who commented (live from Graph) and people who DMed you (from your inbox) -
 * each with a real instagram.com link, plus aggregate follower demographics.
 */
export interface InstagramPerson {
  source: "comment" | "dm";
  ig_id: string | null;
  username: string | null;
  name: string | null;
  text: string | null;
  like_count: number;
  occurred_at: string | null;
  media_id: string | null;
  permalink: string | null;
  profile_url: string | null;
}

export interface InstagramDemographics {
  available: boolean;
  reason: string | null;
  age: { label: string | null; value: number }[];
  gender: { label: string | null; value: number }[];
  cities: { label: string | null; value: number }[];
  countries: { label: string | null; value: number }[];
}

export interface InstagramAudience {
  people: InstagramPerson[];
  demographics: InstagramDemographics;
  comments_unavailable: string | null;
}

export const fetchInstagramAudience = (igId: string): Promise<InstagramAudience> =>
  apiFetch(`/api/v1/meta/instagram/${encodeURIComponent(igId)}/audience`);

export interface InstagramReply {
  id: string | null;
  text: string | null;
  username: string | null;
  timestamp: string | null;
  like_count: number;
  hidden: boolean;
}

export interface InstagramComment {
  id: string | null;
  text: string | null;
  username: string | null;
  name: string | null;
  ig_id: string | null;
  like_count: number;
  timestamp: string | null;
  hidden: boolean;
  media_id: string | null;
  profile_url: string | null;
  replies: InstagramReply[];
}

export interface InstagramChildMedia {
  id: string | null;
  media_type: string | null;
  media_url: string | null;
  thumbnail_url: string | null;
}

export interface InstagramPost {
  id: string | null;
  caption: string | null;
  media_type: string | null;
  /** FEED / REELS / STORY. */
  media_product_type: string | null;
  media_url: string | null;
  /** Static poster frame for videos/carousels (media_url of a video is the file). */
  thumbnail_url: string | null;
  permalink: string | null;
  timestamp: string | null;
  like_count: number;
  comments_count: number;
  children: InstagramChildMedia[];
  comments: InstagramComment[];
}

export interface InstagramPosts {
  posts: InstagramPost[];
  unavailable: string | null;
}

export const fetchInstagramPosts = (igId: string): Promise<InstagramPosts> =>
  apiFetch(`/api/v1/meta/instagram/${encodeURIComponent(igId)}/posts`);

export interface InstagramStory {
  id: string | null;
  media_type: string | null;
  media_url: string | null;
  timestamp: string | null;
}

export interface InstagramStories {
  stories: InstagramStory[];
}

/** The account's own live stories — the only stories edge the API has. */
export const fetchInstagramStories = (igId: string): Promise<InstagramStories> =>
  apiFetch(`/api/v1/meta/instagram/${encodeURIComponent(igId)}/stories`);

export interface InstagramStoredComment {
  id: string;
  comment_id: string | null;
  parent_comment_id: string | null;
  media_id: string | null;
  direction: "inbound" | "outbound";
  content: string;
  author_id: string | null;
  author_name: string | null;
  like_count: number;
  hidden: boolean;
  status: "received" | "sent" | "failed";
  error: string | null;
  platform_timestamp: string | null;
  deleted_at: string | null;
  created_at: string;
}

export interface InstagramComments {
  comments: InstagramStoredComment[];
}

/** The comment inbox — served from stored rows, never a live Graph read. */
export const fetchInstagramComments = (
  igId: string,
  opts?: { mediaId?: string },
): Promise<InstagramComments> =>
  apiFetch(
    `/api/v1/meta/instagram/${encodeURIComponent(igId)}/comments${
      opts?.mediaId ? `?media_id=${encodeURIComponent(opts.mediaId)}` : ""
    }`,
  );

export const replyToInstagramComment = (
  igId: string,
  commentId: string,
  message: string,
): Promise<InstagramStoredComment> =>
  apiFetch(
    `/api/v1/meta/instagram/${encodeURIComponent(igId)}/comments/${encodeURIComponent(commentId)}/replies`,
    { method: "POST", body: JSON.stringify({ message }) },
  );

export const setInstagramCommentHidden = (
  igId: string,
  commentId: string,
  hidden: boolean,
): Promise<{ ok: boolean; hidden: boolean | null }> =>
  apiFetch(
    `/api/v1/meta/instagram/${encodeURIComponent(igId)}/comments/${encodeURIComponent(commentId)}/hide`,
    { method: "POST", body: JSON.stringify({ hidden }) },
  );

export interface InstagramPublishingLimit {
  quota_total: number;
  quota_usage: number;
}

/** Meta's rolling 24h publishing quota; zeros when Meta refused the read. */
export const fetchInstagramPublishingLimit = (
  igId: string,
): Promise<InstagramPublishingLimit> =>
  apiFetch(`/api/v1/meta/instagram/${encodeURIComponent(igId)}/publishing-limit`);

/** Post images to the tenant's own feed — one url or a carousel. The urls
 * must be publicly reachable: Meta's servers fetch them. Story urls are
 * 9:16 crops the client prepared, published as stories after the post. */
export const publishToInstagram = (
  igId: string,
  body: {
    image_urls: string[];
    caption: string;
    location_id?: string;
    share_to_facebook?: boolean;
    alt_text?: string;
    story_image_urls?: string[];
  },
): Promise<{ media_id: string; story_media_ids: string[] }> =>
  apiFetch(`/api/v1/meta/instagram/${encodeURIComponent(igId)}/posts/publish`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export interface InstagramLocation {
  id: string;
  name: string;
}

/** Place search for the location picker; empty when the account can't
 * search (Meta tags places by Facebook Page id — standalone IG can't). */
export const fetchInstagramLocations = (
  igId: string,
  q: string,
): Promise<{ locations: InstagramLocation[] }> =>
  apiFetch(
    `/api/v1/meta/instagram/${encodeURIComponent(igId)}/locations?q=${encodeURIComponent(q)}`,
  );

/** One-shot AI caption draft — nothing is stored or posted; the result
 * lands in the composer's textarea for the tenant to edit and send. */
export const suggestInstagramCaption = (
  igId: string,
  hint: string,
  currentCaption: string,
): Promise<{ caption: string }> =>
  apiFetch(`/api/v1/meta/instagram/${encodeURIComponent(igId)}/caption/suggest`, {
    method: "POST",
    body: JSON.stringify({ hint, current_caption: currentCaption }),
  });

export const deleteInstagramComment = (
  igId: string,
  commentId: string,
): Promise<{ ok: boolean }> =>
  apiFetch(
    `/api/v1/meta/instagram/${encodeURIComponent(igId)}/comments/${encodeURIComponent(commentId)}`,
    { method: "DELETE" },
  );

export interface InstagramMediaInsights {
  available: boolean;
  reason: string | null;
  impressions: number | null;
  reach: number | null;
  saves: number | null;
  shares: number | null;
  views: number | null;
}

/** Owner-only per-post insights, fetched lazily when a post is opened. */
export const fetchInstagramMediaInsights = (
  igId: string,
  mediaId: string,
  mediaType?: string | null
): Promise<InstagramMediaInsights> =>
  apiFetch(
    `/api/v1/meta/instagram/${encodeURIComponent(igId)}/media/${encodeURIComponent(
      mediaId
    )}/insights${mediaType ? `?media_type=${encodeURIComponent(mediaType)}` : ""}`
  );

export const disconnectMeta = (provider: MetaProvider, opts?: { deleteData?: boolean }) =>
  apiFetch(
    `/api/v1/meta/${provider}/disconnect${opts?.deleteData ? "?delete_data=true" : ""}`,
    { method: "DELETE" },
  );
