"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import PostsPage, { normalizePosts, type PostItem } from "@/components/dashboard/PostsPage";
import MediaPage, { normalizeMedia, type MediaItem } from "@/components/dashboard/MediaPage";
import { FeedEmpty, FeedGrid, FeedHeader, feedEntries } from "@/components/dashboard/PostsMediaFeed";
import { useI18n } from "@/lib/i18n/I18nProvider";

/* Unified Posts & Media page.

   One feed shows every post and media item for the selected location; the
   single + Create menu opens the existing composer/dialog surfaces, which
   return here (and refresh the feed) on save, cancel or close. */

interface LocationOption {
  id: string;
  name: string;
}

type Mode =
  | { kind: "feed" }
  | { kind: "post-create" }
  | { kind: "post-detail"; id: string }
  | { kind: "media-create" }
  | { kind: "media-detail"; id: string };

export default function PostsMediaPage() {
  const { t } = useI18n();
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [posts, setPosts] = useState<PostItem[]>([]);
  const [media, setMedia] = useState<MediaItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [feedLoading, setFeedLoading] = useState(false);
  const [mode, setMode] = useState<Mode>({ kind: "feed" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Real locations: every Localith-connected branch (same as both halves).
        try {
          const conns = (await apiFetch("/api/v1/integrations/localith/connections")) as { listing_id: string; listing_name: string }[];
          if (!cancelled && Array.isArray(conns) && conns.length > 0) {
            const locs = conns.map((c) => ({ id: c.listing_id, name: c.listing_name }));
            if (!cancelled) {
              setLocations(locs);
              setSelectedId(locs[0].id);
              return;
            }
          }
        } catch {
          /* fall through to channels */
        }
        const data = await apiFetch("/api/v1/channels?limit=100");
        const googleChannels = (data.channels ?? [])
          .filter((channel: { platform: string }) => channel.platform === "google_reviews")
          .map((channel: { id: string; display_name: string | null }) => ({
            id: channel.id,
            name: channel.display_name ?? "Google location",
          }));
        if (!cancelled) {
          setLocations(googleChannels);
          if (googleChannels.length) setSelectedId(googleChannels[0].id);
        }
      } catch {
        if (!cancelled) {
          setLocations([]);
          setSelectedId(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const loadFeed = useCallback(async () => {
    if (!selectedId) {
      setPosts([]);
      setMedia([]);
      return;
    }
    setFeedLoading(true);
    const q = `?listing_id=${encodeURIComponent(selectedId)}`;
    const [postsRes, mediaRes] = await Promise.allSettled([
      apiFetch(`/api/v1/posts/${q}`),
      apiFetch(`/api/v1/media/${q}`),
    ]);
    setPosts(postsRes.status === "fulfilled" ? normalizePosts(postsRes.value) : []);
    setMedia(mediaRes.status === "fulfilled" ? normalizeMedia(mediaRes.value) : []);
    setFeedLoading(false);
  }, [selectedId]);

  // Refresh when the location changes and whenever a composer/detail returns.
  useEffect(() => {
    if (mode.kind !== "feed") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- refresh after composer/detail returns
    void loadFeed();
  }, [mode.kind, loadFeed]);

  const entries = useMemo(() => feedEntries(posts, media), [posts, media]);

  const stats = useMemo(() => {
    const scheduled = posts.filter((p) => p.status === "SCHEDULED").length;
    return [
      { text: `${posts.length} post${posts.length === 1 ? "" : "s"}`, tone: "violet" as const },
      ...(scheduled > 0 ? [{ text: `${scheduled} scheduled`, tone: "amber" as const }] : []),
      { text: `${media.length} media`, tone: "sky" as const },
    ];
  }, [posts, media]);

  const backToFeed = useCallback(() => setMode({ kind: "feed" }), []);

  if (mode.kind === "post-create" || mode.kind === "post-detail") {
    return (
      <PostsPage
        autoCreate={mode.kind === "post-create"}
        focusId={mode.kind === "post-detail" ? mode.id : null}
        initialLocationId={selectedId}
        onExit={backToFeed}
      />
    );
  }
  if (mode.kind === "media-create" || mode.kind === "media-detail") {
    return (
      <MediaPage
        autoUpload={mode.kind === "media-create"}
        focusMediaId={mode.kind === "media-detail" ? mode.id : null}
        initialLocationId={selectedId}
        onExit={backToFeed}
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <FeedHeader
        title={t.nav.postsMedia}
        subtitle="Publish Google updates and keep every photo ready — one feed for posts and media."
        stats={stats}
        locations={locations}
        selectedId={selectedId}
        onSelectLocation={setSelectedId}
        onCreatePost={() => setMode({ kind: "post-create" })}
        onCreateMedia={() => setMode({ kind: "media-create" })}
      />

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-6xl">
          {loading || (feedLoading && entries.length === 0) ? (
            <div className="flex h-44 items-center justify-center"><LogoLoader size={28} /></div>
          ) : entries.length === 0 ? (
            <FeedEmpty
              hasLocations={locations.length > 0}
              onCreatePost={() => setMode({ kind: "post-create" })}
              onCreateMedia={() => setMode({ kind: "media-create" })}
            />
          ) : (
            <FeedGrid
              entries={entries}
              onOpenPost={(id) => setMode({ kind: "post-detail", id })}
              onOpenMedia={(id) => setMode({ kind: "media-detail", id })}
            />
          )}
        </div>
      </div>
    </div>
  );
}
