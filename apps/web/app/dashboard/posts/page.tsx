"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type PostStatus = "LIVE" | "SCHEDULED" | "ARCHIVED";
type PostTab = "all" | "scheduled" | "archived";
type View = { kind: "list" } | { kind: "create" } | { kind: "detail"; id: string; editing: boolean };

interface PostItem {
  id: string;
  summary: string;
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
];

const MOCK_POSTS: PostItem[] = [
  { id: "p1", summary: "Weekend offer: 20% off all services. Visit us today!", status: "LIVE", createdAt: "2026-09-01", views: 1840 },
  { id: "p2", summary: "New branch opening soon in Olaya. Stay tuned!", status: "SCHEDULED", createdAt: "2026-09-05", scheduledAt: "2026-09-12T10:00", views: 0 },
  { id: "p3", summary: "Eid timings updated. Check our holiday hours.", status: "ARCHIVED", createdAt: "2026-08-20", views: 920 },
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

  const [summary, setSummary] = useState("");
  const [scheduleEnabled, setScheduleEnabled] = useState(false);
  const [scheduledAt, setScheduledAt] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/locations/?limit=100");
        if (!cancelled) {
          setLocations(data.locations ?? []);
          if (data.locations?.length) setSelectedId(data.locations[0].id);
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
        if (!cancelled) setPosts(data.posts ?? MOCK_POSTS);
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

  const openCreate = () => {
    setSummary("");
    setScheduleEnabled(false);
    setScheduledAt("");
    setView({ kind: "create" });
  };

  const openDetail = (id: string, editing = false) => {
    const p = posts.find((x) => x.id === id);
    if (!p) return;
    setSummary(p.summary);
    setScheduleEnabled(p.status === "SCHEDULED");
    setScheduledAt(p.scheduledAt ?? "");
    setView({ kind: "detail", id, editing });
  };

  const backToList = () => setView({ kind: "list" });

  const handleCreate = async () => {
    if (!summary.trim()) return;
    if (scheduleEnabled && !scheduledAt) return;
    setSubmitting(true);
    const status: PostStatus = scheduleEnabled ? "SCHEDULED" : "LIVE";
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts`, {
        method: "POST",
        body: JSON.stringify({ summary: summary.trim(), status, scheduledAt: scheduleEnabled ? scheduledAt : undefined }),
      });
      setPosts((prev) => [{
        id: `p_${Date.now()}`,
        summary: summary.trim(),
        status,
        scheduledAt: scheduleEnabled ? scheduledAt : undefined,
        createdAt: new Date().toISOString().slice(0, 10),
        views: 0,
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
    if (view.kind !== "detail" || !summary.trim()) return;
    if (scheduleEnabled && !scheduledAt) return;
    setSubmitting(true);
    const status: PostStatus = scheduleEnabled ? "SCHEDULED" : activePost?.status === "ARCHIVED" ? "ARCHIVED" : "LIVE";
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts/${view.id}`, {
        method: "PATCH",
        body: JSON.stringify({ summary: summary.trim(), status, scheduledAt: scheduleEnabled ? scheduledAt : undefined }),
      });
      setPosts((prev) => prev.map((p) => p.id === view.id
        ? { ...p, summary: summary.trim(), status, scheduledAt: scheduleEnabled ? scheduledAt : undefined }
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
                    {tab === "all" ? "Create your first post to appear on your Business Profile." : tab === "scheduled" ? "Schedule a post and we will publish it at that time." : "Deleted posts land here and can be restored."}
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
                        <span className="line-clamp-2 flex-1 text-[13px] leading-relaxed text-ink dark:text-fog">{p.summary}</span>
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${p.status === "LIVE" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400" : p.status === "SCHEDULED" ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400" : "bg-ink/[0.05] text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40"}`}>
                          {p.status}
                        </span>
                      </span>
                      <span className="mt-2 block text-[11px] text-ink/35 dark:text-fog/35">
                        Created {p.createdAt} · {p.views.toLocaleString()} views
                        {p.status === "SCHEDULED" && p.scheduledAt ? ` · Publishes ${new Date(p.scheduledAt).toLocaleString()}` : ""}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {view.kind === "create" && (
            <div className="rounded-2xl border border-ink/[0.06] bg-white p-6 dark:border-fog/[0.06] dark:bg-ink">
              <h2 className="text-[15px] font-bold text-ink dark:text-fog">New post</h2>
              <p className="mt-0.5 text-[12px] text-ink/40 dark:text-fog/40">Write once — publish now or schedule for later.</p>
              <div className="mt-5 space-y-4">
                <div>
                  <label className="mb-1 block text-[12px] font-medium text-ink/50">Post text *</label>
                  <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={5} maxLength={1500} placeholder="What do you want customers to know?" className="input-field resize-y" autoFocus />
                  <p className="mt-1 text-right text-[10px] text-ink/30">{summary.length}/1500</p>
                </div>
                <label className="flex cursor-pointer items-center justify-between rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                  <span>
                    <span className="block text-[13px] font-semibold text-ink dark:text-fog">Schedule for later</span>
                    <span className="block text-[11px] text-ink/40">Stored in Sayvors, published via Google at that time.</span>
                  </span>
                  <span onClick={() => setScheduleEnabled(!scheduleEnabled)}
                    className={`h-5 w-9 shrink-0 rounded-full transition ${scheduleEnabled ? "bg-deep-violet" : "bg-ink/15 dark:bg-fog/15"}`}>
                    <span className={`block h-4 w-4 rounded-full bg-white shadow transition-transform ${scheduleEnabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
                  </span>
                </label>
                {scheduleEnabled && (
                  <div>
                    <label className="mb-1 block text-[12px] font-medium text-ink/50">Publish at</label>
                    <input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} className="input-field" />
                  </div>
                )}
                <div className="flex items-center justify-between pt-2">
                  <button onClick={backToList} className="text-[12px] font-medium text-ink/40 hover:text-ink">Back to posts</button>
                  <button onClick={handleCreate} disabled={!summary.trim() || (scheduleEnabled && !scheduledAt) || submitting} className="btn-primary disabled:opacity-50">
                    {submitting ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : scheduleEnabled ? "Schedule Post" : "Publish Post"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {view.kind === "detail" && activePost && (
            <div className="space-y-3">
              <div className="rounded-2xl border border-ink/[0.06] bg-white p-6 dark:border-fog/[0.06] dark:bg-ink">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-[15px] font-bold text-ink dark:text-fog">{view.editing ? "Edit post" : "Post"}</h2>
                  <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${activePost.status === "LIVE" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400" : activePost.status === "SCHEDULED" ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400" : "bg-ink/[0.05] text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40"}`}>
                    {activePost.status}
                  </span>
                </div>
                {view.editing ? (
                  <div className="mt-4 space-y-4">
                    <div>
                      <label className="mb-1 block text-[12px] font-medium text-ink/50">Post text *</label>
                      <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={5} maxLength={1500} className="input-field resize-y" autoFocus />
                    </div>
                    <label className="flex cursor-pointer items-center justify-between rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                      <span className="text-[13px] font-semibold text-ink dark:text-fog">Schedule for later</span>
                      <span onClick={() => setScheduleEnabled(!scheduleEnabled)}
                        className={`h-5 w-9 shrink-0 rounded-full transition ${scheduleEnabled ? "bg-deep-violet" : "bg-ink/15 dark:bg-fog/15"}`}>
                        <span className={`block h-4 w-4 rounded-full bg-white shadow transition-transform ${scheduleEnabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
                      </span>
                    </label>
                    {scheduleEnabled && (
                      <input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} className="input-field" />
                    )}
                    <div className="flex items-center justify-between pt-1">
                      <button onClick={() => openDetail(activePost.id, false)} className="text-[12px] font-medium text-ink/40 hover:text-ink">Cancel editing</button>
                      <button onClick={handleUpdate} disabled={!summary.trim() || submitting} className="btn-primary disabled:opacity-50">
                        {submitting ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : "Save Changes"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="mt-3 text-[14px] leading-relaxed text-ink dark:text-fog">{activePost.summary}</p>
                    <p className="mt-3 text-[11px] text-ink/35 dark:text-fog/35">
                      Created {activePost.createdAt} · {activePost.views.toLocaleString()} views
                      {activePost.status === "SCHEDULED" && activePost.scheduledAt ? ` · Publishes ${new Date(activePost.scheduledAt).toLocaleString()}` : ""}
                    </p>
                    {activePost.status === "SCHEDULED" && (
                      <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-700">Tenant-scheduled — stored locally, published via Google at that time.</p>
                    )}
                    <div className="mt-4 flex flex-wrap gap-2">
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
                  </>
                )}
              </div>
              <button onClick={backToList} className="text-[12px] font-medium text-ink/40 hover:text-ink">← Back to all posts</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
