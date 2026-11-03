"use client";

import { useEffect, useState } from "react";
import { searchAdmin, type AdminSearchGroup } from "@/lib/search-api";

export function useAdminSearch(query: string) {
  const [groups, setGroups] = useState<AdminSearchGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);
  const trimmed = query.trim();

  useEffect(() => {
    if (trimmed.length < 2) return;

    let cancelled = false;
    const timer = setTimeout(() => {
      setLoading(true);
      setError(null);
      searchAdmin(trimmed)
        .then((response) => {
          if (cancelled) return;
          setGroups(response.groups);
          setPreview(Boolean(response.preview));
          setError(null);
        })
        .catch((err) => {
          if (cancelled) return;
          setGroups([]);
          setPreview(false);
          setError(err instanceof Error ? err.message : "Search failed.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 180);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [trimmed]);

  return {
    // Short queries intentionally expose the empty state even if the last
    // completed search is still in state.
    groups: trimmed.length < 2 ? [] : groups,
    loading: trimmed.length < 2 ? false : loading,
    error: trimmed.length < 2 ? null : error,
    preview: trimmed.length < 2 ? false : preview,
  };
}
