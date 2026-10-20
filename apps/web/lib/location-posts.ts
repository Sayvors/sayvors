"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "./api-rag";

/*
 * Location posts are the pre-composer Google posts: one row per branch in
 * the location_posts table, published through Localith by the posts worker.
 * They never pass through the publishing job queue, so the composer's job
 * feed cannot see them — this hook loads them on the same 15s cycle so the
 * posts & media feed shows the whole history, not just composer posts.
 */

export interface LocationPost {
  id: string;
  listing_id: string;
  location_name: string | null;
  business_name: string;
  title: string;
  post_type: "update" | "event" | "offer";
  description: string;
  image_urls: string[];
  status: "draft" | "scheduled" | "published" | "failed" | "archived";
  scheduled_on: string | null;
  published_at: string | null;
  views: number | null;
  cta_clicks: number | null;
  error: string | null;
  created_at: string;
}

export function useLocationPosts() {
  const [posts, setPosts] = useState<LocationPost[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(async (silent = false) => {
    if (!silent) setError(null);
    try {
      const rows = (await apiFetch("/api/v1/posts")) as LocationPost[];
      if (!mounted.current) return;
      setPosts(Array.isArray(rows) ? rows : []);
    } catch (e) {
      if (!mounted.current) return;
      if (!silent) setError(e instanceof Error ? e.message : "Could not load Google posts.");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void refresh();
  }, [refresh]);

  // The posts worker flips scheduled rows to published after mount.
  useEffect(() => {
    const id = setInterval(() => void refresh(true), 15000);
    return () => clearInterval(id);
  }, [refresh]);

  return { posts, error, refresh };
}
