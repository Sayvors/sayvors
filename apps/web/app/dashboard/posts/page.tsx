"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

// ── Future backend contract for scheduled deletion (UI-first: the UI
// speaks it today; the backend ignores unknown fields until it lands).
//   POST /api/v1/posts/            accepts `delete_at: <ISO>|null`
//   PUT  /api/v1/posts/{id}        accepts `delete_at: <ISO>` to schedule,
//                                  `delete_at: null` to cancel
//   GET  /api/v1/posts[/{id}]      echoes `delete_at: <ISO>|null`
//   worker                         deletes rows whose delete_at has passed
// Until GET echoes it, this page keeps a session overlay (deleteOverlay)
// so a just-saved schedule stays visible across refreshes.

type PostStatus = "LIVE" | "SCHEDULED" | "ARCHIVED" | "DRAFT" | "FAILED";
type PostTab = "all" | "scheduled" | "archived";
type View = { kind: "list" } | { kind: "create" } | { kind: "detail"; id: string; editing: boolean };

interface PostItem {
  id: string;
  title: string;
  locationId: string;
  locationName: string;
  businessName: string;
  description: string;
  tags: string[];
  keywords: string[];
  images: string[];
  status: PostStatus;
  createdAt: string;
  scheduledAt?: string;
  // Auto-deletion time (ISO). Absent = no scheduled deletion.
  deleteAt?: string;
}

interface LocationOption {
  id: string;
  name: string;
}

const BACKEND_STATUS: Record<string, PostStatus> = {
  published: "LIVE",
  scheduled: "SCHEDULED",
  archived: "ARCHIVED",
  draft: "DRAFT",
  failed: "FAILED",
};

export default function PostsPage() {
  return (
    <Suspense>
      <PostsInner />
    </Suspense>
  );
}

function PostsInner() {
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [posts, setPosts] = useState<PostItem[]>([]);
  const [tab, setTab] = useState<PostTab>("all");
  const [view, setView] = useState<View>({ kind: "list" });
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const [title, setTitle] = useState("");
  const [postLocationId, setPostLocationId] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [keywords, setKeywords] = useState<string[]>([]);
  const [keywordInput, setKeywordInput] = useState("");
  const [images, setImages] = useState<string[]>([]);
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduledAt, setScheduledAt] = useState("");
  const [deleteEnabled, setDeleteEnabled] = useState(false);
  const [deleteAt, setDeleteAt] = useState("");
  // Session overlay for scheduled deletion until the backend echoes
  // delete_at (see contract note at top). Key present = overlay wins:
  // ISO string = pending schedule, null = pending cancel.
  const [deleteOverlay, setDeleteOverlay] = useState<Record<string, string | null>>({});
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Real locations: every Localith-connected branch.
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
        const data = await apiFetch("/api/v1/channels/?limit=100");
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

  const loadPosts = async (overlay?: Record<string, string | null>) => {
    const q = selectedId ? `?listing_id=${encodeURIComponent(selectedId)}` : "";
    const data = await apiFetch(`/api/v1/posts/${q}`);
    return normalizePosts(data, overlay ?? deleteOverlay);
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const items = await loadPosts();
        if (!cancelled) setPosts(items);
      } catch {
        if (!cancelled) setPosts([]);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const counts = useMemo(() => ({
    all: posts.filter((p) => p.status === "LIVE").length,
    scheduled: posts.filter((p) => p.status === "SCHEDULED").length,
    archived: posts.filter((p) => p.status === "ARCHIVED").length,
  }), [posts]);

  const filtered = posts.filter((p) => {
    if (tab === "scheduled") return p.status === "SCHEDULED";
    if (tab === "archived") return p.status === "ARCHIVED";
    return p.status === "LIVE" || p.status === "FAILED" || p.status === "DRAFT";
  });

  const activePost = view.kind === "detail" ? posts.find((p) => p.id === view.id) ?? null : null;

  const resetForm = (locId?: string) => {
    setTitle("");
    setPostLocationId(locId ?? selectedId ?? locations[0]?.id ?? "");
    setBusinessName("Sayvors");
    setDescription("");
    setTags([]);
    setTagInput("");
    setKeywords([]);
    setKeywordInput("");
    setImages([]);
    setScheduleEnabled(false);
    setScheduledAt("");
    setDeleteEnabled(false);
    setDeleteAt("");
  };

  const openCreate = () => {
    resetForm();
    setView({ kind: "create" });
  };

  const openDetail = (id: string, editing = false) => {
    const p = posts.find((x) => x.id === id);
    if (!p) return;
    setTitle(p.title);
    setPostLocationId(p.locationId);
    setBusinessName(p.businessName);
    setDescription(p.description);
    setTags(p.tags);
    setKeywords(p.keywords);
    setImages(p.images);
    setScheduleEnabled(p.status === "SCHEDULED");
    setScheduledAt((p.scheduledAt ?? "").slice(0, 16));
    setDeleteEnabled(!!p.deleteAt);
    setDeleteAt((p.deleteAt ?? "").slice(0, 16));
    setView({ kind: "detail", id, editing });
  };

  const backToList = () => setView({ kind: "list" });

  const addChip = (value: string, list: string[], setList: (v: string[]) => void) => {
    const v = value.trim().toLowerCase();
    if (v && !list.includes(v)) setList([...list, v]);
  };

  const handleFiles = (files: FileList | null) => {
    if (!files) return;
    const names = Array.from(files).slice(0, 5).map((f) => f.name);
    setImages((prev) => [...prev, ...names].slice(0, 5));
  };

  // Scheduled deletion must be in the future — and after the scheduled
  // publish time when both are set.
  const deleteErr = (() => {
    if (!deleteEnabled) return null;
    if (!deleteAt) return "Pick a deletion date and time.";
    const t = new Date(deleteAt).getTime();
    if (Number.isNaN(t)) return "Pick a valid date and time.";
    if (t <= Date.now()) return "Deletion must be in the future.";
    if (scheduleEnabled && scheduledAt) {
      const s = new Date(scheduledAt).getTime();
      if (!Number.isNaN(s) && t <= s) return "Deletion must be after the scheduled publish time.";
    }
    return null;
  })();

  const valid = title.trim() && businessName.trim() && description.trim() && postLocationId && (!scheduleEnabled || scheduledAt) && !deleteErr;

  const showBannerTimed = (kind: "ok" | "err", text: string) => {
    setBanner({ kind, text });
    setTimeout(() => setBanner(null), 4000);
  };

  const refreshPosts = async (overlay?: Record<string, string | null>) => {
    try {
      setPosts(await loadPosts(overlay));
    } catch {
      /* keep current list on failure */
    }
  };

  const handleCreate = async () => {
    if (!valid) return;
    setSubmitting(true);
    try {
      const res = await apiFetch("/api/v1/posts/", {
        method: "POST",
        body: JSON.stringify({
          listing_id: postLocationId,
          location_name: locations.find((l) => l.id === postLocationId)?.name ?? "",
          business_name: businessName.trim(),
          title: title.trim(),
          description: description.trim(),
          tags,
          keywords,
          image_urls: images,
          action: scheduleEnabled ? "schedule" : "publish",
          scheduled_on: scheduleEnabled && scheduledAt ? new Date(scheduledAt).toISOString() : null,
          // Future contract (ignored by the backend until scheduled
          // deletion lands — see note at top).
          delete_at: deleteEnabled && deleteAt ? new Date(deleteAt).toISOString() : null,
        }),
      });
      const newId = res?.post?.id ?? res?.id;
      let nextOverlay = deleteOverlay;
      if (deleteEnabled && deleteAt && newId) {
        nextOverlay = { ...deleteOverlay, [String(newId)]: new Date(deleteAt).toISOString() };
        setDeleteOverlay(nextOverlay);
      }
      await refreshPosts(nextOverlay);
      setView({ kind: "list" });
      const skipped = res?.images_skipped ?? 0;
      showBannerTimed("ok", scheduleEnabled
        ? "Post scheduled — our worker will publish it to Google at that time."
        : `Published to Google.${skipped ? ` ${skipped} local image(s) not sent — attach hosted URLs to include images.` : ""}`);
    } catch (e) {
      showBannerTimed("err", e instanceof Error ? e.message.slice(0, 200) : "Could not save post.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdate = async () => {
    if (view.kind !== "detail" || !valid) return;
    setSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        location_name: locations.find((l) => l.id === postLocationId)?.name ?? "",
        business_name: businessName.trim(),
        title: title.trim(),
        description: description.trim(),
        tags,
        keywords,
        image_urls: images,
      };
      if (scheduleEnabled) {
        body.status = "scheduled";
        body.scheduled_on = scheduledAt ? new Date(scheduledAt).toISOString() : null;
      } else if (activePost?.status === "SCHEDULED" || activePost?.status === "DRAFT") {
        body.status = "draft";
        body.scheduled_on = null;
      }
      // Future contract: schedule / cancel auto-deletion (ignored by the
      // backend until scheduled deletion lands — see note at top).
      if (deleteEnabled && deleteAt) {
        body.delete_at = new Date(deleteAt).toISOString();
      } else if (activePost?.deleteAt) {
        body.delete_at = null;
      }
      await apiFetch(`/api/v1/posts/${view.id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      let nextOverlay = deleteOverlay;
      if (deleteEnabled && deleteAt) {
        nextOverlay = { ...deleteOverlay, [view.id]: new Date(deleteAt).toISOString() };
        setDeleteOverlay(nextOverlay);
      } else if (activePost?.deleteAt) {
        nextOverlay = { ...deleteOverlay, [view.id]: null };
        setDeleteOverlay(nextOverlay);
      }
      await refreshPosts(nextOverlay);
      setView({ kind: "detail", id: view.id, editing: false });
      showBannerTimed("ok", "Post updated.");
    } catch (e) {
      showBannerTimed("err", e instanceof Error ? e.message.slice(0, 200) : "Could not update post.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this post permanently? Published copies on Google stay.")) return;
    try {
      await apiFetch(`/api/v1/posts/${id}`, { method: "DELETE" });
      setPosts((prev) => prev.filter((p) => p.id !== id));
      setDeleteOverlay((prev) => {
        if (!(id in prev)) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
      showBannerTimed("ok", "Post deleted.");
    } catch {
      showBannerTimed("err", "Could not delete post.");
    }
    setView({ kind: "list" });
  };

  const handleCancelDeletion = async (id: string) => {
    try {
      await apiFetch(`/api/v1/posts/${id}`, {
        method: "PUT",
        body: JSON.stringify({ delete_at: null }),
      });
      const nextOverlay = { ...deleteOverlay, [id]: null };
      setDeleteOverlay(nextOverlay);
      await refreshPosts(nextOverlay);
      showBannerTimed("ok", "Scheduled deletion cancelled.");
    } catch (e) {
      showBannerTimed("err", e instanceof Error ? e.message.slice(0, 200) : "Could not cancel scheduled deletion.");
    }
  };

  const handleArchive = async (id: string) => {
    try {
      await apiFetch(`/api/v1/posts/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: "archived" }),
      });
      await refreshPosts();
      showBannerTimed("ok", "Post archived.");
    } catch {
      showBannerTimed("err", "Could not archive post.");
    }
    setView({ kind: "list" });
  };

  const handleRestore = async (id: string) => {
    try {
      await apiFetch(`/api/v1/posts/${id}`, {
        method: "PUT",
        body: JSON.stringify({ status: "published" }),
      });
      await refreshPosts();
      showBannerTimed("ok", "Post restored (already live on Google — not re-published).");
      setView({ kind: "detail", id, editing: false });
    } catch {
      showBannerTimed("err", "Could not restore post.");
    }
  };

  const handlePublishNow = async (id: string) => {
    try {
      const res = await apiFetch(`/api/v1/posts/${id}/publish`, { method: "POST" });
      await refreshPosts();
      const skipped = res?.images_skipped ?? 0;
      showBannerTimed("ok", `Published to Google.${skipped ? ` ${skipped} local image(s) not sent.` : ""}`);
    } catch (e) {
      showBannerTimed("err", e instanceof Error ? e.message.slice(0, 200) : "Publish failed.");
      await refreshPosts();
    }
  };

  if (loading) return <div className="flex h-full items-center justify-center"><LogoLoader size={32} /></div>;

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-ink/[0.06] bg-white/80 px-6 py-4 backdrop-blur dark:border-fog/[0.06] dark:bg-ink/80">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-[18px] font-bold text-ink dark:text-fog">Posts</h1>
            <p className="text-[12px] text-ink/40 dark:text-fog/40">{counts.all} live · {counts.scheduled} scheduled · {counts.archived} archived</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value)}
                className="w-52 appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none dark:border-fog/[0.1] dark:bg-ink dark:text-fog">
                {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
              </select>
              <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </div>
            {view.kind === "list" && (
              <button onClick={openCreate} className="rounded-xl bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:opacity-90">
                + Create Post
              </button>
            )}
          </div>
        </div>
        {banner && (
          <div className={`mt-3 rounded-lg px-3 py-1.5 text-[12px] font-medium ${banner.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{banner.text}</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-3xl space-y-4">
          {view.kind !== "list" && (
            <nav className="flex items-center gap-1.5 text-[12px] text-ink/40 dark:text-fog/40">
              <button onClick={backToList} className="font-medium hover:text-deep-violet">Posts</button>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" /></svg>
              <span className="font-semibold text-ink dark:text-fog">
                {view.kind === "create" ? "Create Post" : view.editing ? "Edit Post" : "Post Details"}
              </span>
            </nav>
          )}

          {view.kind === "list" && (
            <>
              <div className="flex gap-1 overflow-x-auto rounded-xl bg-ink/[0.03] p-1 dark:bg-fog/[0.04]">
                {([
                  { key: "all", label: `All Posts (${counts.all})` },
                  { key: "scheduled", label: `Scheduled (${counts.scheduled})` },
                  { key: "archived", label: `Archived (${counts.archived})` },
                ] as const).map((t) => (
                  <button key={t.key} onClick={() => setTab(t.key)}
                    className={`whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-semibold transition ${tab === t.key ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-fog" : "text-ink/45 hover:text-ink/70 dark:text-fog/45"}`}>
                    {t.label}
                  </button>
                ))}
              </div>

              {filtered.length === 0 ? (
                <div className="flex flex-col items-center rounded-2xl border border-dashed border-ink/[0.12] bg-white py-16 dark:border-fog/[0.12] dark:bg-ink">
                  <p className="text-[14px] font-medium text-ink/40 dark:text-fog/40">
                    {tab === "scheduled" ? "No scheduled posts" : tab === "archived" ? "No archived posts" : "No posts yet"}
                  </p>
                  <p className="mt-1 max-w-sm text-center text-[12px] text-ink/30 dark:text-fog/30">
                    Give it a title, description, tags, keywords and images.
                  </p>
                  {tab === "all" && (
                    <button onClick={openCreate} className="mt-4 rounded-xl bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white">+ Create Post</button>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  {filtered.map((p) => (
                    <button key={p.id} onClick={() => openDetail(p.id, false)} className="block w-full rounded-2xl border border-ink/[0.06] bg-white p-4 text-left transition hover:border-deep-violet/25 hover:shadow-sm dark:border-fog/[0.06] dark:bg-ink">
                      <span className="flex items-start justify-between gap-3">
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14px] font-bold text-ink dark:text-fog">{p.title}</span>
                          <span className="mt-0.5 block text-[11px] text-ink/40 dark:text-fog/40">{p.businessName} · {p.locationName}</span>
                        </span>
                        <StatusBadge status={p.status} />
                      </span>
                      <span className="mt-2 line-clamp-2 block text-[13px] leading-relaxed text-ink/70 dark:text-fog/70">{p.description}</span>
                      <span className="mt-2 flex flex-wrap items-center gap-1.5">
                        {p.tags.slice(0, 3).map((t) => (
                          <span key={t} className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-semibold text-deep-violet">#{t}</span>
                        ))}
                        {p.images.length > 0 && (
                          <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-medium text-ink/50 dark:bg-fog/[0.06]">📷 {p.images.length}</span>
                        )}
                        {p.status === "SCHEDULED" && p.scheduledAt && (
                          <span className="ml-auto text-[11px] text-ink/35 dark:text-fog/35">Publishes {new Date(p.scheduledAt).toLocaleString()}</span>
                        )}
                        {p.deleteAt && (
                          <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700 dark:bg-red-500/10 dark:text-red-400">
                            🗑 {new Date(p.deleteAt).toLocaleString()}
                          </span>
                        )}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {view.kind === "create" && (
            <PostForm
              title={title} setTitle={setTitle}
              postLocationId={postLocationId} setPostLocationId={setPostLocationId} locations={locations}
              businessName={businessName} setBusinessName={setBusinessName}
              description={description} setDescription={setDescription}
              tags={tags} tagInput={tagInput} setTagInput={setTagInput}
              onAddTag={() => { addChip(tagInput, tags, setTags); setTagInput(""); }}
              onRemoveTag={(t) => setTags(tags.filter((x) => x !== t))}
              keywords={keywords} keywordInput={keywordInput} setKeywordInput={setKeywordInput}
              onAddKeyword={() => { addChip(keywordInput, keywords, setKeywords); setKeywordInput(""); }}
              onRemoveKeyword={(k) => setKeywords(keywords.filter((x) => x !== k))}
              images={images} onFiles={handleFiles} onRemoveImage={(n) => setImages(images.filter((x) => x !== n))}
              scheduleEnabled={scheduleEnabled} setScheduleEnabled={setScheduleEnabled}
              scheduledAt={scheduledAt} setScheduledAt={setScheduledAt}
              deleteEnabled={deleteEnabled} setDeleteEnabled={setDeleteEnabled}
              deleteAt={deleteAt} setDeleteAt={setDeleteAt}
              deleteErr={deleteErr}
              onBack={backToList} onSubmit={handleCreate} submitting={submitting}
              submitLabel={scheduleEnabled ? "Schedule Post" : "Publish Post"}
              heading="New post" subheading="Title, location, description, tags, keywords and images."
            />
          )}

          {view.kind === "detail" && activePost && (
            <div className="space-y-3">
              {view.editing ? (
                <PostForm
                  title={title} setTitle={setTitle}
                  postLocationId={postLocationId} setPostLocationId={setPostLocationId} locations={locations}
                  businessName={businessName} setBusinessName={setBusinessName}
                  description={description} setDescription={setDescription}
                  tags={tags} tagInput={tagInput} setTagInput={setTagInput}
                  onAddTag={() => { addChip(tagInput, tags, setTags); setTagInput(""); }}
                  onRemoveTag={(t) => setTags(tags.filter((x) => x !== t))}
                  keywords={keywords} keywordInput={keywordInput} setKeywordInput={setKeywordInput}
                  onAddKeyword={() => { addChip(keywordInput, keywords, setKeywords); setKeywordInput(""); }}
                  onRemoveKeyword={(k) => setKeywords(keywords.filter((x) => x !== k))}
                  images={images} onFiles={handleFiles} onRemoveImage={(n) => setImages(images.filter((x) => x !== n))}
                  scheduleEnabled={scheduleEnabled} setScheduleEnabled={setScheduleEnabled}
                  scheduledAt={scheduledAt} setScheduledAt={setScheduledAt}
                  deleteEnabled={deleteEnabled} setDeleteEnabled={setDeleteEnabled}
                  deleteAt={deleteAt} setDeleteAt={setDeleteAt}
                  deleteErr={deleteErr}
                  onBack={() => openDetail(activePost.id, false)} onSubmit={handleUpdate} submitting={submitting}
                  submitLabel="Save Changes" heading="Edit post" subheading="Update every field, then save."
                />
              ) : (
                <div className="overflow-hidden rounded-2xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
                  {activePost.images.length > 0 && (
                    <div className="grid grid-cols-3 gap-1 bg-ink/[0.03] p-2 dark:bg-fog/[0.03]">
                      {activePost.images.map((img) => (
                        <div key={img} className="flex aspect-video items-center justify-center rounded-lg bg-gradient-to-br from-violet-soft/40 to-sky/20 px-2 text-center">
                          <span className="truncate text-[10px] font-medium text-ink/50">{img}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="p-6">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <h2 className="text-[17px] font-bold text-ink dark:text-fog">{activePost.title}</h2>
                        <p className="mt-0.5 text-[12px] text-ink/40 dark:text-fog/40">{activePost.businessName} · {activePost.locationName}</p>
                      </div>
                      <StatusBadge status={activePost.status} />
                    </div>
                    <p className="mt-3 text-[13px] leading-relaxed text-ink/80 dark:text-fog/80">{activePost.description}</p>
                    {activePost.tags.length > 0 && (
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {activePost.tags.map((t) => (
                          <span key={t} className="rounded-full bg-deep-violet/10 px-2.5 py-1 text-[11px] font-semibold text-deep-violet">#{t}</span>
                        ))}
                      </div>
                    )}
                    {activePost.keywords.length > 0 && (
                      <p className="mt-2 text-[11px] text-ink/40 dark:text-fog/40">Keywords: {activePost.keywords.join(", ")}</p>
                    )}
                    <p className="mt-3 text-[11px] text-ink/35 dark:text-fog/35">
                      Created {activePost.createdAt}
                      {activePost.status === "SCHEDULED" && activePost.scheduledAt ? ` · Publishes ${new Date(activePost.scheduledAt).toLocaleString()}` : ""}
                    </p>
                    {activePost.deleteAt && (
                      <p className="mt-2 flex flex-wrap items-center gap-2 rounded-xl bg-red-50 px-3 py-2 text-[12px] font-medium text-red-700 dark:bg-red-500/10 dark:text-red-300">
                        <span>🗑 Scheduled deletion {new Date(activePost.deleteAt).toLocaleString()}</span>
                        <button onClick={() => handleCancelDeletion(activePost.id)} className="ml-auto rounded-lg border border-red-200 px-2.5 py-1 text-[11px] font-semibold hover:bg-red-100 dark:hover:bg-red-500/20">
                          Cancel deletion
                        </button>
                      </p>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2 border-t border-ink/[0.05] pt-4">
                      {activePost.status !== "ARCHIVED" && (
                        <button onClick={() => openDetail(activePost.id, true)} className="btn-secondary">Edit</button>
                      )}
                      {(activePost.status === "SCHEDULED" || activePost.status === "FAILED" || activePost.status === "DRAFT") && (
                        <button onClick={() => handlePublishNow(activePost.id)} className="rounded-xl bg-emerald-500 px-4 py-2 text-[12px] font-semibold text-white hover:bg-emerald-600">
                          {activePost.status === "FAILED" ? "Retry publish" : "Publish now"}
                        </button>
                      )}
                      {activePost.status !== "ARCHIVED" ? (
                        <>
                          <button onClick={() => handleArchive(activePost.id)} className="rounded-xl border border-ink/[0.1] px-4 py-2 text-[12px] font-semibold text-ink/50 hover:bg-ink/[0.04] dark:text-fog/50">Archive</button>
                          <button onClick={() => handleDelete(activePost.id)} className="rounded-xl border border-red-200 px-4 py-2 text-[12px] font-semibold text-red-600 hover:bg-red-50">Delete</button>
                        </>
                      ) : (
                        <button onClick={() => handleRestore(activePost.id)} className="btn-primary">Restore</button>
                      )}
                    </div>
                  </div>
                </div>
              )}
              <button onClick={backToList} className="text-[12px] font-medium text-ink/40 hover:text-ink">← Back to all posts</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: PostStatus }) {
  const cls =
    status === "LIVE"
      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400"
      : status === "SCHEDULED"
        ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400"
        : status === "FAILED"
          ? "bg-red-100 text-red-700 dark:bg-red-500/10 dark:text-red-400"
          : status === "DRAFT"
            ? "bg-sky-100 text-sky-700 dark:bg-sky-500/10 dark:text-sky-400"
            : "bg-ink/[0.05] text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40";
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${cls}`}>
      {status}
    </span>
  );
}

function normalizePosts(raw: unknown, deleteOverlay?: Record<string, string | null>): PostItem[] {
  if (!Array.isArray(raw)) return [];
  return (raw as Record<string, unknown>[]).map((p: Record<string, unknown>, i: number) => {
    const id = String(p.id ?? `p_${i}`);
    const backendDelete = p.delete_at ? String(p.delete_at) : p.deleteAt ? String(p.deleteAt) : undefined;
    const overlayDelete = deleteOverlay && id in deleteOverlay ? deleteOverlay[id] : undefined;
    return {
      id,
      title: String(p.title ?? "Untitled post"),
      locationId: String(p.listing_id ?? p.locationId ?? p.location_id ?? ""),
      locationName: String(p.location_name ?? p.locationName ?? ""),
      businessName: String(p.business_name ?? p.businessName ?? "Sayvors"),
      description: String(p.description ?? ""),
      tags: Array.isArray(p.tags) ? p.tags.map(String) : [],
      keywords: Array.isArray(p.keywords) ? p.keywords.map(String) : [],
      images: Array.isArray(p.image_urls ?? p.images) ? ((p.image_urls ?? p.images) as unknown[]).map(String) : [],
      status: BACKEND_STATUS[String(p.status)] ?? "DRAFT",
      createdAt: String(p.created_at ?? p.createdAt ?? new Date().toISOString().slice(0, 10)).slice(0, 10),
      scheduledAt: p.scheduled_on ? String(p.scheduled_on) : p.scheduledAt ? String(p.scheduledAt) : undefined,
      deleteAt: backendDelete ?? overlayDelete ?? undefined,
    };
  });
}

function PostForm(props: {
  title: string; setTitle: (v: string) => void;
  postLocationId: string; setPostLocationId: (v: string) => void; locations: LocationOption[];
  businessName: string; setBusinessName: (v: string) => void;
  description: string; setDescription: (v: string) => void;
  tags: string[]; tagInput: string; setTagInput: (v: string) => void; onAddTag: () => void; onRemoveTag: (t: string) => void;
  keywords: string[]; keywordInput: string; setKeywordInput: (v: string) => void; onAddKeyword: () => void; onRemoveKeyword: (k: string) => void;
  images: string[]; onFiles: (f: FileList | null) => void; onRemoveImage: (n: string) => void;
  scheduleEnabled: boolean; setScheduleEnabled: (v: boolean) => void;
  scheduledAt: string; setScheduledAt: (v: string) => void;
  deleteEnabled: boolean; setDeleteEnabled: (v: boolean) => void;
  deleteAt: string; setDeleteAt: (v: string) => void;
  deleteErr: string | null;
  onBack: () => void; onSubmit: () => void; submitting: boolean;
  submitLabel: string; heading: string; subheading: string;
}) {
  const p = props;
  return (
    <div className="rounded-2xl border border-ink/[0.06] bg-white p-6 dark:border-fog/[0.06] dark:bg-ink">
      <h2 className="text-[15px] font-bold text-ink dark:text-fog">{p.heading}</h2>
      <p className="mt-0.5 text-[12px] text-ink/40 dark:text-fog/40">{p.subheading}</p>
      <div className="mt-5 space-y-4">
        <div>
          <label className="mb-1 block text-[12px] font-medium text-ink/50">Title *</label>
          <input value={p.title} onChange={(e) => p.setTitle(e.target.value)} placeholder="e.g. Weekend Offer — 20% Off" className="input-field" autoFocus />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-[12px] font-medium text-ink/50">Location *</label>
            <select value={p.postLocationId} onChange={(e) => p.setPostLocationId(e.target.value)} className="input-field">
              {p.locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[12px] font-medium text-ink/50">Business name *</label>
            <input value={p.businessName} onChange={(e) => p.setBusinessName(e.target.value)} placeholder="Sayvors" className="input-field" />
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[12px] font-medium text-ink/50">Description *</label>
          <textarea value={p.description} onChange={(e) => p.setDescription(e.target.value)} rows={4} maxLength={1500} placeholder="Full post text customers will see..." className="input-field resize-y" />
        </div>
        <div>
          <label className="mb-1 block text-[12px] font-medium text-ink/50">Tags</label>
          <div className="flex flex-wrap gap-1.5">
            {p.tags.map((t) => (
              <span key={t} className="inline-flex items-center gap-1 rounded-full bg-deep-violet/10 px-2.5 py-1 text-[11px] font-semibold text-deep-violet">
                #{t}
                <button onClick={() => p.onRemoveTag(t)} className="opacity-50 hover:opacity-100">✕</button>
              </span>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <input value={p.tagInput} onChange={(e) => p.setTagInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && p.onAddTag()} placeholder="Add tag + Enter" className="input-field flex-1" />
            <button onClick={p.onAddTag} className="btn-secondary">Add</button>
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[12px] font-medium text-ink/50">Keywords</label>
          <div className="flex flex-wrap gap-1.5">
            {p.keywords.map((k) => (
              <span key={k} className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2.5 py-1 text-[11px] font-medium text-sky-700">
                {k}
                <button onClick={() => p.onRemoveKeyword(k)} className="opacity-50 hover:opacity-100">✕</button>
              </span>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <input value={p.keywordInput} onChange={(e) => p.setKeywordInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && p.onAddKeyword()} placeholder="Add keyword + Enter" className="input-field flex-1" />
            <button onClick={p.onAddKeyword} className="btn-secondary">Add</button>
          </div>
        </div>
        <div>
          <label className="mb-1 block text-[12px] font-medium text-ink/50">Images (up to 5)</label>
          <label className="flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed border-ink/[0.12] py-6 text-[12px] text-ink/40">
            <span>Click to attach images</span>
            <input type="file" accept="image/*" multiple className="hidden" onChange={(e) => p.onFiles(e.target.files)} />
          </label>
          {p.images.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {p.images.map((n) => (
                <span key={n} className="inline-flex items-center gap-1 rounded-lg bg-ink/[0.04] px-2 py-1 text-[11px] text-ink/60">
                  {n}
                  <button onClick={() => p.onRemoveImage(n)} className="opacity-50 hover:opacity-100">✕</button>
                </span>
              ))}
            </div>
          )}
        </div>
        <label className="flex cursor-pointer items-center justify-between rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
          <span>
            <span className="block text-[13px] font-semibold text-ink dark:text-fog">Schedule for later</span>
            <span className="block text-[11px] text-ink/40">Stored in Sayvors, published via Google at that time.</span>
          </span>
          <span onClick={() => p.setScheduleEnabled(!p.scheduleEnabled)}
            className={`h-5 w-9 shrink-0 rounded-full transition ${p.scheduleEnabled ? "bg-deep-violet" : "bg-ink/15 dark:bg-fog/15"}`}>
            <span className={`block h-4 w-4 rounded-full bg-white shadow transition-transform ${p.scheduleEnabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
          </span>
        </label>
        {p.scheduleEnabled && (
          <input type="datetime-local" value={p.scheduledAt} onChange={(e) => p.setScheduledAt(e.target.value)} className="input-field" />
        )}
        <label className="flex cursor-pointer items-center justify-between rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
          <span>
            <span className="block text-[13px] font-semibold text-ink dark:text-fog">Schedule deletion</span>
            <span className="block text-[11px] text-ink/40">Auto-delete this post at that time (Google copy stays).</span>
          </span>
          <span onClick={() => p.setDeleteEnabled(!p.deleteEnabled)}
            className={`h-5 w-9 shrink-0 rounded-full transition ${p.deleteEnabled ? "bg-red-500" : "bg-ink/15 dark:bg-fog/15"}`}>
            <span className={`block h-4 w-4 rounded-full bg-white shadow transition-transform ${p.deleteEnabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
          </span>
        </label>
        {p.deleteEnabled && (
          <div>
            <input type="datetime-local" value={p.deleteAt} onChange={(e) => p.setDeleteAt(e.target.value)} className="input-field" />
            {p.deleteErr && <p className="mt-1 text-[11px] font-medium text-red-600">{p.deleteErr}</p>}
          </div>
        )}
        <div className="flex items-center justify-between pt-1">
          <button onClick={p.onBack} className="text-[12px] font-medium text-ink/40 hover:text-ink">Back</button>
          <button onClick={p.onSubmit} disabled={p.submitting} className="btn-primary disabled:opacity-50">
            {p.submitting ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : p.submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
