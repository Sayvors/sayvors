"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type PostStatus = "LIVE" | "SCHEDULED" | "ARCHIVED";
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
  views: number;
}

interface LocationOption {
  id: string;
  name: string;
}

const MOCK_LOCATIONS: LocationOption[] = [
  { id: "loc_1", name: "Sayvors Al Malqa" },
  { id: "loc_2", name: "Sayvors Olaya" },
];

const MOCK_POSTS: PostItem[] = [
  {
    id: "p1", title: "Weekend Offer — 20% Off", locationId: "loc_1", locationName: "Sayvors Al Malqa",
    businessName: "Sayvors", description: "Weekend offer: 20% off all services. Visit us today and bring a friend!",
    tags: ["offer", "weekend"], keywords: ["discount", "services", "riyadh"], images: ["offer-banner.jpg"],
    status: "LIVE", createdAt: "2026-09-01", views: 1840,
  },
  {
    id: "p2", title: "New Branch Opening Soon", locationId: "loc_2", locationName: "Sayvors Olaya",
    businessName: "Sayvors", description: "New branch opening soon in Olaya. Stay tuned for launch offers!",
    tags: ["announcement"], keywords: ["new branch", "olaya"], images: [],
    status: "SCHEDULED", createdAt: "2026-09-05", scheduledAt: "2026-09-12T10:00", views: 0,
  },
  {
    id: "p3", title: "Eid Timings Update", locationId: "loc_1", locationName: "Sayvors Al Malqa",
    businessName: "Sayvors", description: "Eid timings updated. Check our holiday hours before visiting.",
    tags: ["hours", "holiday"], keywords: ["eid", "timings"], images: [],
    status: "ARCHIVED", createdAt: "2026-08-20", views: 920,
  },
];

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
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/locations/?limit=100");
        if (!cancelled) {
          const locs = data.locations ?? MOCK_LOCATIONS;
          setLocations(locs);
          if (locs.length) setSelectedId(locs[0].id);
        }
      } catch {
        setLocations(MOCK_LOCATIONS);
        setSelectedId(MOCK_LOCATIONS[0].id);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch(`/api/v1/locations/${selectedId}/posts`);
        if (!cancelled) setPosts(normalizePosts(data.posts) ?? MOCK_POSTS);
      } catch {
        if (!cancelled) setPosts(MOCK_POSTS);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedId]);

  const counts = useMemo(() => ({
    all: posts.filter((p) => p.status === "LIVE").length,
    scheduled: posts.filter((p) => p.status === "SCHEDULED").length,
    archived: posts.filter((p) => p.status === "ARCHIVED").length,
  }), [posts]);

  const filtered = posts.filter((p) => {
    if (tab === "scheduled") return p.status === "SCHEDULED";
    if (tab === "archived") return p.status === "ARCHIVED";
    return p.status === "LIVE";
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
    setScheduledAt(p.scheduledAt ?? "");
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

  const valid = title.trim() && businessName.trim() && description.trim() && postLocationId && (!scheduleEnabled || scheduledAt);

  const payload = () => {
    const loc = locations.find((l) => l.id === postLocationId);
    return {
      title: title.trim(),
      locationId: postLocationId,
      locationName: loc?.name ?? "",
      businessName: businessName.trim(),
      description: description.trim(),
      tags,
      keywords,
      images,
    };
  };

  const handleCreate = async () => {
    if (!valid) return;
    setSubmitting(true);
    const status: PostStatus = scheduleEnabled ? "SCHEDULED" : "LIVE";
    const base = payload();
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts`, {
        method: "POST",
        body: JSON.stringify({ ...base, status, scheduledAt: scheduleEnabled ? scheduledAt : undefined }),
      });
      setPosts((prev) => [{
        id: `p_${Date.now()}`, ...base,
        status, scheduledAt: scheduleEnabled ? scheduledAt : undefined,
        createdAt: new Date().toISOString().slice(0, 10), views: 0,
      }, ...prev]);
      setView({ kind: "list" });
      setBanner({ kind: "ok", text: scheduleEnabled ? "Post scheduled. We will publish it via Google at that time." : "Post published." });
      setTimeout(() => setBanner(null), 2500);
    } catch {
      setBanner({ kind: "err", text: "Could not save post." });
    }
    setSubmitting(false);
  };

  const handleUpdate = async () => {
    if (view.kind !== "detail" || !valid) return;
    setSubmitting(true);
    const status: PostStatus = scheduleEnabled ? "SCHEDULED" : activePost?.status === "ARCHIVED" ? "ARCHIVED" : "LIVE";
    const base = payload();
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts/${view.id}`, {
        method: "PATCH",
        body: JSON.stringify({ ...base, status, scheduledAt: scheduleEnabled ? scheduledAt : undefined }),
      });
      setPosts((prev) => prev.map((p) => p.id === view.id
        ? { ...p, ...base, status, scheduledAt: scheduleEnabled ? scheduledAt : undefined }
        : p));
      setView({ kind: "detail", id: view.id, editing: false });
      setBanner({ kind: "ok", text: "Post updated." });
      setTimeout(() => setBanner(null), 2500);
    } catch {
      setBanner({ kind: "err", text: "Could not update post." });
    }
    setSubmitting(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts/${id}`, { method: "DELETE" });
    } catch { /* optimistic */ }
    setPosts((prev) => prev.map((p) => p.id === id ? { ...p, status: "ARCHIVED" as PostStatus } : p));
    setView({ kind: "list" });
  };

  const handleRestore = async (id: string) => {
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "LIVE" }),
      });
    } catch { /* optimistic */ }
    setPosts((prev) => prev.map((p) => p.id === id ? { ...p, status: "LIVE" as PostStatus } : p));
    setView({ kind: "detail", id, editing: false });
  };

  const handlePublishNow = async (id: string) => {
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "LIVE" }),
      });
    } catch { /* optimistic */ }
    setPosts((prev) => prev.map((p) => p.id === id ? { ...p, status: "LIVE" as PostStatus, scheduledAt: undefined } : p));
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
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${p.status === "LIVE" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400" : p.status === "SCHEDULED" ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400" : "bg-ink/[0.05] text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40"}`}>
                          {p.status}
                        </span>
                      </span>
                      <span className="mt-2 line-clamp-2 block text-[13px] leading-relaxed text-ink/70 dark:text-fog/70">{p.description}</span>
                      <span className="mt-2 flex flex-wrap items-center gap-1.5">
                        {p.tags.slice(0, 3).map((t) => (
                          <span key={t} className="rounded-full bg-deep-violet/10 px-2 py-0.5 text-[10px] font-semibold text-deep-violet">#{t}</span>
                        ))}
                        {p.images.length > 0 && (
                          <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-medium text-ink/50 dark:bg-fog/[0.06]">📷 {p.images.length}</span>
                        )}
                        <span className="ml-auto text-[11px] text-ink/35 dark:text-fog/35">{p.views.toLocaleString()} views{p.status === "SCHEDULED" && p.scheduledAt ? ` · ${new Date(p.scheduledAt).toLocaleString()}` : ""}</span>
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
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${activePost.status === "LIVE" ? "bg-emerald-100 text-emerald-700" : activePost.status === "SCHEDULED" ? "bg-amber-100 text-amber-700" : "bg-ink/[0.05] text-ink/40"}`}>
                        {activePost.status}
                      </span>
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
                      Created {activePost.createdAt} · {activePost.views.toLocaleString()} views
                      {activePost.status === "SCHEDULED" && activePost.scheduledAt ? ` · Publishes ${new Date(activePost.scheduledAt).toLocaleString()}` : ""}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-2 border-t border-ink/[0.05] pt-4">
                      {activePost.status !== "ARCHIVED" && (
                        <button onClick={() => openDetail(activePost.id, true)} className="btn-secondary">Edit</button>
                      )}
                      {activePost.status === "SCHEDULED" && (
                        <button onClick={() => handlePublishNow(activePost.id)} className="rounded-xl bg-emerald-500 px-4 py-2 text-[12px] font-semibold text-white hover:bg-emerald-600">Publish now</button>
                      )}
                      {activePost.status !== "ARCHIVED" ? (
                        <button onClick={() => handleDelete(activePost.id)} className="rounded-xl border border-red-200 px-4 py-2 text-[12px] font-semibold text-red-600 hover:bg-red-50">Delete</button>
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

function normalizePosts(raw: unknown): PostItem[] | null {
  if (!Array.isArray(raw)) return null;
  return raw.map((p: Record<string, unknown>, i: number) => ({
    id: String(p.id ?? `p_${i}`),
    title: String(p.title ?? p.summary ?? "Untitled post"),
    locationId: String(p.locationId ?? p.location_id ?? "loc_1"),
    locationName: String(p.locationName ?? p.location_name ?? ""),
    businessName: String(p.businessName ?? p.business_name ?? "Sayvors"),
    description: String(p.description ?? p.summary ?? ""),
    tags: Array.isArray(p.tags) ? p.tags.map(String) : [],
    keywords: Array.isArray(p.keywords) ? p.keywords.map(String) : [],
    images: Array.isArray(p.images) ? p.images.map(String) : [],
    status: (p.status as PostStatus) ?? "LIVE",
    createdAt: String(p.createdAt ?? p.created_at ?? new Date().toISOString().slice(0, 10)),
    scheduledAt: p.scheduledAt ? String(p.scheduledAt) : p.scheduled_at ? String(p.scheduled_at) : undefined,
    views: Number(p.views ?? 0),
  }));
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
