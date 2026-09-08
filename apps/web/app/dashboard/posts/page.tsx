"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";

type PostStatus = "LIVE" | "SCHEDULED" | "ARCHIVED";
type PostTab = "all" | "scheduled" | "archived";

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
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<PostItem | null>(null);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Create/edit form
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

  const openCreate = () => {
    setEditing(null);
    setSummary("");
    setScheduleEnabled(false);
    setScheduledAt("");
    setShowCreate(true);
  };

  const openEdit = (p: PostItem) => {
    setEditing(p);
    setSummary(p.summary);
    setScheduleEnabled(p.status === "SCHEDULED");
    setScheduledAt(p.scheduledAt ?? "");
    setShowCreate(true);
  };

  const handleSubmit = async () => {
    if (!summary.trim()) return;
    if (scheduleEnabled && !scheduledAt) return;
    setSubmitting(true);
    const status: PostStatus = scheduleEnabled ? "SCHEDULED" : "LIVE";
    try {
      if (editing) {
        await apiFetch(`/api/v1/locations/${selectedId}/posts/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify({ summary: summary.trim(), status, scheduledAt: scheduleEnabled ? scheduledAt : undefined }),
        });
        setPosts((prev) => prev.map((p) => p.id === editing.id
          ? { ...p, summary: summary.trim(), status, scheduledAt: scheduleEnabled ? scheduledAt : undefined }
          : p));
      } else {
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
      }
      setShowCreate(false);
      setBanner({ kind: "ok", text: scheduleEnabled ? "Post scheduled. We will publish it via Google at that time." : "Post published." });
      setTimeout(() => setBanner(null), 2500);
    } catch {
      setBanner({ kind: "err", text: "Could not save post." });
    }
    setSubmitting(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts/${id}`, { method: "DELETE" });
    } catch { /* optimistic */ }
    setPosts((prev) => prev.map((p) => p.id === id ? { ...p, status: "ARCHIVED" as PostStatus } : p));
  };

  const handleRestore = async (id: string) => {
    try {
      await apiFetch(`/api/v1/locations/${selectedId}/posts/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: "LIVE" }),
      });
    } catch { /* optimistic */ }
    setPosts((prev) => prev.map((p) => p.id === id ? { ...p, status: "LIVE" as PostStatus } : p));
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
            <button onClick={openCreate} className="rounded-xl bg-deep-violet px-4 py-2 text-[13px] font-semibold text-white transition hover:opacity-90">
              + Create Post
            </button>
          </div>
        </div>
        {banner && (
          <div className={`mt-3 rounded-lg px-3 py-1.5 text-[12px] font-medium ${banner.kind === "ok" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{banner.text}</div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="mx-auto max-w-3xl space-y-4">
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
                <div key={p.id} className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                  <div className="flex items-start justify-between gap-3">
                    <p className="flex-1 text-[13px] leading-relaxed text-ink dark:text-fog">{p.summary}</p>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${p.status === "LIVE" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400" : p.status === "SCHEDULED" ? "bg-amber-100 text-amber-700 dark:bg-amber-500/10 dark:text-amber-400" : "bg-ink/[0.05] text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40"}`}>
                      {p.status}
                    </span>
                  </div>
                  <p className="mt-2 text-[11px] text-ink/35 dark:text-fog/35">
                    Created {p.createdAt} · {p.views.toLocaleString()} views
                    {p.status === "SCHEDULED" && p.scheduledAt ? ` · Publishes ${new Date(p.scheduledAt).toLocaleString()}` : ""}
                  </p>
                  {p.status === "SCHEDULED" && (
                    <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">Tenant-scheduled — stored locally, published via Google at that time.</p>
                  )}
                  <div className="mt-3 flex flex-wrap gap-2">
                    {p.status !== "ARCHIVED" && (
                      <button onClick={() => openEdit(p)} className="rounded-lg border border-ink/[0.08] px-3 py-1.5 text-[11px] font-semibold text-ink/60 hover:bg-ink/[0.03] dark:border-fog/[0.08] dark:text-fog/60">Edit</button>
                    )}
                    {p.status === "SCHEDULED" && (
                      <button onClick={() => handlePublishNow(p.id)} className="rounded-lg bg-emerald-500 px-3 py-1.5 text-[11px] font-semibold text-white hover:bg-emerald-600">Publish now</button>
                    )}
                    {p.status !== "ARCHIVED" ? (
                      <button onClick={() => handleDelete(p.id)} className="rounded-lg border border-red-200 px-3 py-1.5 text-[11px] font-semibold text-red-600 hover:bg-red-50">Delete</button>
                    ) : (
                      <button onClick={() => handleRestore(p.id)} className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white hover:opacity-90">Restore</button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setShowCreate(false)}>
          <div className="w-full max-w-md rounded-2xl bg-white shadow-2xl dark:bg-ink" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-ink/[0.06] px-5 py-4 dark:border-fog/[0.06]">
              <h2 className="text-[15px] font-bold text-ink dark:text-fog">{editing ? "Edit Post" : "Create Post"}</h2>
              <button onClick={() => setShowCreate(false)} className="text-ink/30 hover:text-ink/60"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg></button>
            </div>
            <div className="space-y-4 p-5">
              <div>
                <label className="mb-1 block text-[12px] font-medium text-ink/50">Post text *</label>
                <textarea value={summary} onChange={(e) => setSummary(e.target.value)} rows={4} maxLength={1500} placeholder="What do you want customers to know?" className="input-field resize-y" autoFocus />
                <p className="mt-1 text-right text-[10px] text-ink/30">{summary.length}/1500</p>
              </div>
              <label className="flex cursor-pointer items-center justify-between rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.06]">
                <span>
                  <span className="block text-[13px] font-semibold text-ink dark:text-fog">Schedule for later</span>
                  <span className="block text-[11px] text-ink/40">Stored in Sayvors, published via Google at that time.</span>
                </span>
                <button
                  onClick={() => setScheduleEnabled(!scheduleEnabled)}
                  className={`h-5 w-9 shrink-0 rounded-full transition ${scheduleEnabled ? "bg-deep-violet" : "bg-ink/15 dark:bg-fog/15"}`}>
                  <span className={`block h-4 w-4 rounded-full bg-white shadow transition-transform ${scheduleEnabled ? "translate-x-[18px]" : "translate-x-0.5"}`} />
                </button>
              </label>
              {scheduleEnabled && (
                <div>
                  <label className="mb-1 block text-[12px] font-medium text-ink/50">Publish at</label>
                  <input type="datetime-local" value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} className="input-field" />
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2 border-t border-ink/[0.06] px-5 py-3 dark:border-fog/[0.06]">
              <button onClick={() => setShowCreate(false)} className="btn-secondary">Cancel</button>
              <button onClick={handleSubmit} disabled={!summary.trim() || (scheduleEnabled && !scheduledAt) || submitting} className="btn-primary disabled:opacity-50">
                {submitting ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving...</span> : scheduleEnabled ? "Schedule Post" : editing ? "Save Changes" : "Publish Post"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
