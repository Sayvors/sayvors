"use client";

import Link from "next/link";
import { useEffect, useState, Fragment, useMemo } from "react";
import {
  listDatabanks,
  deleteDatabank,
  listDocuments,
  retryDocuments,
  previewDocument,
  type DatabankDoc,
  type DocumentPreview,
} from "@/lib/api-rag";

type Databank = {
  id: string;
  name: string;
  description?: string;
  accent_color?: string;
  doc_count?: number;
  total_size?: number;
};

function formatBytes(bytes = 0): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const size = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / 1024 ** size;
  return `${value.toFixed(1)} ${units[size]}`;
}

function StatusBadge({ status }: { status?: string }) {
  const base = "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold tracking-wide";
  if (status === "ready" || status === "completed" || status === "processed") {
    return (
      <span className={`${base} bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200/60`}>
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        Ready
      </span>
    );
  }
  if (status === "processing") {
    return (
      <span className={`${base} bg-amber-50 text-amber-700 ring-1 ring-amber-200/60`}>
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
        Processing
      </span>
    );
  }
  if (status === "pending" || status === "queued") {
    return (
      <span
        title="Waiting to be parsed"
        className={`${base} bg-sky-50 text-sky-700 ring-1 ring-sky-200/60`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-sky-500" />
        Queued
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className={`${base} bg-red-50 text-red-600 ring-1 ring-red-200/60`}>
        <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
        Failed
      </span>
    );
  }
  return (
    <span className={`${base} bg-ink/5 text-ink/40`}>
      {status || "Unknown"}
    </span>
  );
}

function FileIcon({ type }: { type?: string }) {
  const t = (type || "").toLowerCase();
  if (t.includes("pdf")) {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-red-50 text-red-600 ring-1 ring-red-200/50">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M10 13H8v4h2a2 2 0 000-4z M14 13h-1v4h1a2 2 0 002-2 2 2 0 00-2-2z" />
        </svg>
      </span>
    );
  }
  if (t.includes("csv") || t.includes("xls")) {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200/50">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 14h8M8 17h8" />
        </svg>
      </span>
    );
  }
  if (t.includes("doc")) {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-50 text-sky-600 ring-1 ring-sky-200/50">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 13h6M8 17h6" />
        </svg>
      </span>
    );
  }
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink/[0.06] text-ink/40">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <path d="M14 2v6h6" />
      </svg>
    </span>
  );
}

export default function DatabankPage() {
  const [databanks, setDatabanks] = useState<Databank[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [docs, setDocs] = useState<DatabankDoc[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [processing, setProcessing] = useState<string | null>(null);
  const [previewDocId, setPreviewDocId] = useState<string | null>(null);
  const [preview, setPreview] = useState<DocumentPreview | null>(null);
  const [previewPage, setPreviewPage] = useState(1);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    async function load() {
      try {
        const data = await listDatabanks();
        const list = Array.isArray(data) ? data : data?.databanks ?? [];
        setDatabanks(list);
        if (list.length > 0 && !selectedId) setSelectedId(list[0].id);
      } catch {
        setDatabanks([]);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  const selected = databanks.find((db) => db.id === selectedId) ?? null;

  useEffect(() => {
    if (!selectedId) {
      setDocs([]);
      return;
    }
    let cancelled = false;
    async function loadDocs() {
      setDocsLoading(true);
      try {
        const data = await listDocuments(selectedId!);
        if (!cancelled) setDocs(Array.isArray(data) ? data : data?.documents ?? []);
      } catch {
        if (!cancelled) setDocs([]);
      } finally {
        if (!cancelled) setDocsLoading(false);
      }
    }
    void loadDocs();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const confirmDeleteDb = confirmDeleteId ? databanks.find((d) => d.id === confirmDeleteId) ?? null : null;

  async function confirmDelete() {
    if (!confirmDeleteId) return;
    const id = confirmDeleteId;
    setDeleting(true);
    try {
      await deleteDatabank(id);
      setDatabanks((prev) => prev.filter((db) => db.id !== id));
      if (selectedId === id) setSelectedId(databanks.find((d) => d.id !== id)?.id ?? null);
      setConfirmDeleteId(null);
    } catch {}
    finally {
      setDeleting(false);
    }
  }

  async function refreshDocs() {
    if (!selectedId) return;
    try {
      const data = await listDocuments(selectedId);
      setDocs(Array.isArray(data) ? data : data?.documents ?? []);
    } catch {}
  }

  async function handleRetryDoc(docId: string) {
    if (!selectedId) return;
    setProcessing(docId);
    try {
      await retryDocuments(selectedId, [docId]);
      setTimeout(() => {
        void refreshDocs().finally(() => setProcessing(null));
      }, 2000);
    } catch {
      setProcessing(null);
    }
  }

  async function handleRetryAll() {
    if (!selectedId) return;
    setProcessing("all");
    try {
      await retryDocuments(selectedId);
      setTimeout(() => {
        void refreshDocs().finally(() => setProcessing(null));
      }, 2000);
    } catch {
      setProcessing(null);
    }
  }

  const filteredDocs = useMemo(() => {
    return docs.filter((d) => {
      const name = (d.filename || d.name || "").toLowerCase();
      const matchesQ = !q || name.includes(q.toLowerCase());
      const matchesFilter = filter === "all" || d.status === filter;
      return matchesQ && matchesFilter;
    });
  }, [docs, q, filter]);

  const stuckCount = docs.filter(
    (d) => d.status === "pending" || d.status === "queued" || d.status === "processing" || d.status === "failed"
  ).length;

  const totalDocs = databanks.reduce((a, b) => a + (b.doc_count ?? 0), 0);
  const totalSize = databanks.reduce((a, b) => a + (b.total_size ?? 0), 0);
  const readyDocs = docs.filter((d) => d.status === "ready" || d.status === "completed" || d.status === "processed").length;

  async function loadPreview(docId: string, page: number) {
    if (!selectedId) return;
    setPreviewLoading(true);
    try {
      const data = await previewDocument(selectedId, docId, page, 25);
      setPreview(data);
      setPreviewDocId(docId);
      setPreviewPage(page);
    } catch {
      setPreview(null);
    } finally {
      setPreviewLoading(false);
    }
  }

  function togglePreview(docId: string) {
    if (previewDocId === docId) {
      setPreviewDocId(null);
      setPreview(null);
    } else {
      void loadPreview(docId, 1);
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-[#f8f7ff]">
      <div className="space-y-6 p-4 sm:p-6">
        {/* Company Header */}
        <div className="overflow-hidden rounded-[20px] border border-white bg-white shadow-sm">
          <div className="bg-gradient-to-r from-deep-violet via-[#4c2a8a] to-[#6d28d9] px-6 py-5">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-white/15 text-white backdrop-blur ring-1 ring-white/20">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-6 w-6">
                    <ellipse cx="12" cy="5" rx="9" ry="3" />
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                  </svg>
                </div>
                <div>
                  <h1 className="text-[20px] font-bold tracking-tight text-white sm:text-[22px]">Knowledge Base</h1>
                  <p className="mt-0.5 text-[12px] font-medium text-white/70 sm:text-[13px]">
                    Power your AI agents with company documents, sites & data
                  </p>
                </div>
              </div>
              <Link
                href="/dashboard/databank/new"
                className="inline-flex items-center justify-center gap-1.5 self-start rounded-xl bg-white px-4 py-2.5 text-[12px] font-bold text-deep-violet shadow-sm transition hover:bg-white/90 active:scale-[0.98] sm:self-auto"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="h-3.5 w-3.5">
                  <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                </svg>
                New Databank
              </Link>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl bg-white/10 px-3 py-3 ring-1 ring-white/10 backdrop-blur">
                <div className="text-[10px] font-bold uppercase tracking-widest text-white/60">Databanks</div>
                <div className="mt-1 text-[20px] font-bold text-white">{databanks.length}</div>
              </div>
              <div className="rounded-xl bg-white/10 px-3 py-3 ring-1 ring-white/10 backdrop-blur">
                <div className="text-[10px] font-bold uppercase tracking-widest text-white/60">Documents</div>
                <div className="mt-1 text-[20px] font-bold text-white">{totalDocs}</div>
              </div>
              <div className="rounded-xl bg-white/10 px-3 py-3 ring-1 ring-white/10 backdrop-blur">
                <div className="text-[10px] font-bold uppercase tracking-widest text-white/60">Storage</div>
                <div className="mt-1 text-[20px] font-bold text-white">{formatBytes(totalSize)}</div>
              </div>
              <div className="rounded-xl bg-white/10 px-3 py-3 ring-1 ring-white/10 backdrop-blur">
                <div className="text-[10px] font-bold uppercase tracking-widest text-white/60">AI Ready</div>
                <div className="mt-1 flex items-baseline gap-1.5 text-[20px] font-bold text-white">
                  {readyDocs}
                  <span className="text-[11px] font-medium text-white/60">/ {docs.length} in view</span>
                </div>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 px-6 py-3 text-[11px] font-medium text-ink/50">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald-500" /> Live indexing
            </span>
            <span className="text-ink/20">•</span>
            <span>Secure & private to your workspace</span>
            <span className="ml-auto hidden items-center gap-1 text-ink/40 sm:inline-flex">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-3.5 w-3.5">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
              Enterprise-grade
            </span>
          </div>
        </div>

        {/* Databank Grid */}
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[13px] font-bold uppercase tracking-widest text-ink/40">Your databanks</h2>
            <span className="text-[11px] font-medium text-ink/30">{databanks.length} total</span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {loading
              ? Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="animate-pulse rounded-2xl border border-white bg-white p-5">
                    <div className="h-10 w-10 rounded-xl bg-ink/[0.06]" />
                    <div className="mt-4 h-4 w-32 rounded bg-ink/[0.06]" />
                    <div className="mt-2 h-3 w-20 rounded bg-ink/[0.04]" />
                  </div>
                ))
              : databanks.map((db) => {
                  const isSelected = selectedId === db.id;
                  return (
                    <div
                      key={db.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setSelectedId(isSelected ? null : db.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setSelectedId(isSelected ? null : db.id);
                        }
                      }}
                      className={[
                        "group relative overflow-hidden rounded-2xl border bg-white p-5 text-left transition-all",
                        isSelected
                          ? "border-deep-violet shadow-lg shadow-deep-violet/10 ring-1 ring-deep-violet/10"
                          : "border-ink/[0.06] hover:border-deep-violet/20 hover:shadow-md",
                      ].join(" ")}
                    >
                      {isSelected && <div className="absolute inset-x-0 top-0 h-1 bg-deep-violet" />}
                      <div className="flex items-start justify-between gap-3">
                        <div
                          className="flex h-11 w-11 items-center justify-center rounded-xl text-white shadow-sm"
                          style={{ backgroundColor: db.accent_color || "#3d1d6e" }}
                        >
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-5 w-5">
                            <ellipse cx="12" cy="5" rx="9" ry="3" />
                            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                          </svg>
                        </div>
                        <div className="flex items-center gap-1">
                          {isSelected && (
                            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-deep-violet text-white">
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3 w-3">
                                <path d="M5 12l7 7 7-7" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </span>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDeleteId(db.id);
                            }}
                            className="rounded-lg p-1.5 text-ink/20 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                            title="Delete databank"
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5">
                              <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6M10 11v6M14 11v6" />
                            </svg>
                          </button>
                        </div>
                      </div>
                      <div className="mt-4 text-[15px] font-bold leading-tight text-ink">{db.name}</div>
                      <div className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-ink/50">
                        {db.description || "No description — add one to help your team."}
                      </div>
                      <div className="mt-4 flex items-center gap-2">
                        <span className="inline-flex items-center gap-1 rounded-full bg-ink/[0.06] px-2.5 py-1 text-[11px] font-semibold text-ink/60">
                          <span className="h-1.5 w-1.5 rounded-full bg-deep-violet" />
                          {db.doc_count ?? 0} docs
                        </span>
                        <span className="text-[11px] font-medium text-ink/30">{formatBytes(db.total_size ?? 0)}</span>
                        {isSelected && <span className="ml-auto text-[11px] font-bold text-deep-violet">Selected</span>}
                      </div>
                    </div>
                  );
                })}
          </div>
        </div>

        {!loading && databanks.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-[20px] border-2 border-dashed border-deep-violet/15 bg-white px-6 py-16 text-center shadow-sm">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet to-[#6d28d9] text-white shadow-lg shadow-deep-violet/20">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-8 w-8">
                <ellipse cx="12" cy="5" rx="9" ry="3" />
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
              </svg>
            </div>
            <h2 className="mt-5 text-[18px] font-bold tracking-tight text-ink">Create your first databank</h2>
            <p className="mt-2 max-w-md text-[13px] leading-relaxed text-ink/50">
              Upload files, crawl your website, or connect a database. Your AI will search it instantly.
            </p>
            <Link
              href="/dashboard/databank/new"
              className="mt-6 inline-flex items-center gap-1.5 rounded-xl bg-deep-violet px-6 py-2.5 text-[13px] font-bold text-white shadow-md shadow-deep-violet/20 transition hover:bg-deep-violet/90 active:scale-[0.98]"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="h-4 w-4">
                <path d="M12 5v14M5 12h14" strokeLinecap="round" />
              </svg>
              Create Databank
            </Link>
          </div>
        )}

        {/* Selected databank detail */}
        {selected && (
          <div className="overflow-hidden rounded-[20px] border border-white bg-white shadow-[0_12px_32px_rgba(58,39,120,0.08)]">
            <div className="flex flex-col gap-3 border-b border-ink/[0.06] bg-gradient-to-r from-white to-[#faf8ff] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <div
                  className="flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-sm"
                  style={{ backgroundColor: selected.accent_color || "#3d1d6e" }}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5">
                    <ellipse cx="12" cy="5" rx="9" ry="3" />
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-[16px] font-bold leading-tight text-ink">{selected.name}</h2>
                  {selected.description && <p className="text-[12px] text-ink/50">{selected.description}</p>}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="hidden items-center gap-1.5 rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-bold text-emerald-700 ring-1 ring-emerald-200/50 sm:inline-flex">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Live
                </span>
                <Link
                  href="/dashboard/databank/new"
                  className="inline-flex items-center gap-1.5 rounded-xl bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-deep-violet/90"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                    <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                  </svg>
                  Add source
                </Link>
              </div>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 divide-x divide-ink/[0.06] border-b border-ink/[0.06] bg-ink/[0.015]">
              <div className="px-5 py-4">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-ink/40">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-3 w-3">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                    <path d="M14 2v6h6" />
                  </svg>
                  Documents
                </div>
                <div className="mt-1 text-[22px] font-bold tracking-tight text-ink">{selected.doc_count ?? docs.length}</div>
              </div>
              <div className="px-5 py-4">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-ink/40">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-3 w-3">
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                  </svg>
                  Storage
                </div>
                <div className="mt-1 text-[22px] font-bold tracking-tight text-ink">{formatBytes(selected.total_size ?? 0)}</div>
              </div>
              <div className="px-5 py-4">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-ink/40">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" /> AI Search
                </div>
                <div className="mt-1 text-[13px] font-bold">
                  {docs.some((d) => d.status === "completed" || d.status === "ready") ? (
                    <span className="text-emerald-600">Active — ready to answer</span>
                  ) : docsLoading ? (
                    <span className="text-ink/40">Checking…</span>
                  ) : (
                    <span className="text-ink/40">No indexed data</span>
                  )}
                </div>
              </div>
            </div>

            {/* Toolbar */}
            <div className="flex flex-col gap-3 border-b border-ink/[0.06] bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-1 items-center gap-2">
                <div className="relative flex-1 sm:max-w-xs">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink/30">
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
                  </svg>
                  <input
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder="Search documents…"
                    className="w-full rounded-xl border border-ink/10 bg-ink/[0.02] py-2 pl-8 pr-3 text-[12px] font-medium text-ink placeholder:text-ink/30 outline-none transition focus:border-deep-violet/30 focus:bg-white"
                  />
                </div>
                <select
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="rounded-xl border border-ink/10 bg-white px-2.5 py-2 text-[12px] font-semibold text-ink/60 outline-none focus:border-deep-violet/30"
                >
                  <option value="all">All statuses</option>
                  <option value="ready">Ready</option>
                  <option value="processing">Processing</option>
                  <option value="pending">Queued</option>
                  <option value="failed">Failed</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <span className="hidden text-[11px] font-medium text-ink/40 sm:block">
                  {filteredDocs.length} of {docs.length}
                </span>
                {stuckCount > 0 && (
                  <button
                    type="button"
                    onClick={() => void handleRetryAll()}
                    disabled={processing === "all"}
                    className="inline-flex items-center gap-1.5 rounded-xl bg-deep-violet px-3.5 py-2 text-[11px] font-bold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
                      <path d="M21 12a9 9 0 11-9-9" strokeLinecap="round" />
                      <path d="M9 9l3-3 3 3M9 15l3 3 3-3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {processing === "all" ? "Retrying…" : `Retry ${stuckCount}`}
                  </button>
                )}
              </div>
            </div>

            {/* Table */}
            {docsLoading ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-14 animate-pulse rounded-xl bg-ink/[0.04]" />
                ))}
              </div>
            ) : filteredDocs.length === 0 ? (
              <div className="flex flex-col items-center px-6 py-12 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-ink/[0.04] text-ink/20">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-6 w-6">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M14 2v6h6" />
                  </svg>
                </div>
                <p className="mt-3 text-[13px] font-semibold text-ink/60">
                  {q || filter !== "all" ? "No matching documents" : "No documents yet"}
                </p>
                <p className="mt-1 max-w-sm text-[12px] leading-relaxed text-ink/35">
                  {q || filter !== "all" ? "Try a different search or filter." : "Upload a CSV, PDF, or text file to make your AI smarter."}
                </p>
                {!q && filter === "all" && (
                  <Link href="/dashboard/databank/new" className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-deep-violet/10 px-4 py-2 text-[12px] font-bold text-deep-violet transition hover:bg-deep-violet/15">
                    Add your first source
                  </Link>
                )}
              </div>
            ) : (
              <div className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-ink/[0.06] bg-ink/[0.02] text-left">
                        <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-ink/40">File</th>
                        <th className="hidden px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-ink/40 sm:table-cell">Type</th>
                        <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-ink/40">Size</th>
                        <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-ink/40">Status</th>
                        <th className="px-4 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-ink/40">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink/[0.04]">
                      {filteredDocs.map((doc) => (
                        <Fragment key={doc.id}>
                          <tr className="group transition hover:bg-ink/[0.015]">
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-3">
                                <FileIcon type={doc.file_type} />
                                <div className="min-w-0">
                                  <div className="truncate text-[12px] font-semibold text-ink">{doc.filename || doc.name || doc.id}</div>
                                  <div className="text-[11px] text-ink/35 sm:hidden">{doc.file_type || "—"} · {formatBytes(doc.file_size ?? 0)}</div>
                                </div>
                              </div>
                            </td>
                            <td className="hidden px-3 py-3 sm:table-cell">
                              <span className="inline-flex rounded-md bg-ink/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/50">
                                {doc.file_type || "—"}
                              </span>
                            </td>
                            <td className="px-3 py-3 text-[12px] font-medium tabular-nums text-ink/50">{formatBytes(doc.file_size ?? 0)}</td>
                            <td className="px-3 py-3">
                              <StatusBadge status={doc.status} />
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center justify-end gap-1">
                                <button
                                  type="button"
                                  onClick={() => togglePreview(doc.id)}
                                  className={`rounded-lg px-2.5 py-1 text-[11px] font-semibold transition ${previewDocId === doc.id ? "bg-ink text-white" : "border border-ink/10 bg-white text-ink/60 hover:bg-ink/[0.04]"}`}
                                >
                                  {previewDocId === doc.id ? "Hide" : "View"}
                                </button>
                                {(doc.status === "pending" || doc.status === "queued" || doc.status === "processing" || doc.status === "failed") && (
                                  <button
                                    type="button"
                                    onClick={() => void handleRetryDoc(doc.id)}
                                    disabled={processing === doc.id}
                                    className="rounded-lg bg-deep-violet/10 px-2.5 py-1 text-[11px] font-bold text-deep-violet transition hover:bg-deep-violet/15 disabled:opacity-50"
                                  >
                                    {processing === doc.id ? "…" : "Retry"}
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {previewDocId === doc.id && (
                            <tr className="bg-ink/[0.015]">
                              <td colSpan={5} className="px-4 py-4">
                                {previewLoading ? (
                                  <div className="space-y-2">
                                    {Array.from({ length: 3 }).map((_, i) => (
                                      <div key={i} className="h-10 animate-pulse rounded-xl bg-ink/[0.05]" />
                                    ))}
                                  </div>
                                ) : !preview ? (
                                  <p className="py-2 text-center text-[12px] text-ink/40">Could not load content.</p>
                                ) : preview.kind === "table" ? (
                                  <div className="overflow-hidden rounded-xl border border-ink/[0.08] bg-white shadow-sm">
                                    <div className="flex items-center justify-between border-b border-ink/[0.06] bg-ink/[0.02] px-3 py-2">
                                      <span className="text-[11px] font-bold text-ink/60">
                                        {preview.total} rows · {preview.columns?.length ?? 0} cols
                                      </span>
                                      <span className="text-[11px] font-medium text-ink/30">Page {previewPage}</span>
                                    </div>
                                    <div className="overflow-x-auto">
                                      <table className="w-full text-[12px]">
                                        <thead>
                                          <tr className="border-b border-ink/[0.08] bg-ink/[0.03]">
                                            {(preview.columns ?? []).map((col) => (
                                              <th key={col} className="whitespace-nowrap px-3 py-2 text-left text-[11px] font-bold text-ink/60">
                                                {col}
                                              </th>
                                            ))}
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {(preview.rows ?? []).map((row, ri) => (
                                            <tr key={ri} className="border-b border-ink/[0.04] last:border-0 hover:bg-ink/[0.015]">
                                              {(preview.columns ?? []).map((col) => (
                                                <td key={col} className="max-w-[200px] truncate px-3 py-2 text-ink/70">
                                                  {row[col] ?? ""}
                                                </td>
                                              ))}
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                    {preview.total > preview.page_size && (
                                      <div className="flex items-center justify-between border-t border-ink/[0.06] bg-ink/[0.015] px-3 py-2">
                                        <button
                                          type="button"
                                          disabled={previewPage <= 1 || previewLoading}
                                          onClick={() => void loadPreview(doc.id, previewPage - 1)}
                                          className="rounded-lg border border-ink/10 bg-white px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:bg-ink/[0.03] disabled:opacity-30"
                                        >
                                          ← Prev
                                        </button>
                                        <span className="text-[11px] font-medium text-ink/40">
                                          Page {previewPage} of {Math.ceil(preview.total / preview.page_size)}
                                        </span>
                                        <button
                                          type="button"
                                          disabled={previewPage >= Math.ceil(preview.total / preview.page_size) || previewLoading}
                                          onClick={() => void loadPreview(doc.id, previewPage + 1)}
                                          className="rounded-lg border border-ink/10 bg-white px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:bg-ink/[0.03] disabled:opacity-30"
                                        >
                                          Next →
                                        </button>
                                      </div>
                                    )}
                                  </div>
                                ) : (
                                  <div className="rounded-xl border border-ink/[0.06] bg-white p-4 shadow-sm">
                                    <p className="mb-3 text-[11px] font-bold uppercase tracking-wide text-ink/40">
                                      {preview.total} chunks — what the AI actually searches
                                    </p>
                                    <div className="space-y-2">
                                      {(preview.chunks ?? []).map((c, i) => (
                                        <p key={i} className="rounded-xl bg-ink/[0.03] px-3 py-2.5 text-[12px] leading-relaxed text-ink/65">
                                          {c}
                                        </p>
                                      ))}
                                      {(preview.chunks ?? []).length === 0 && (
                                        <p className="py-2 text-center text-[12px] text-ink/40">No parsed content yet — still processing.</p>
                                      )}
                                    </div>
                                  </div>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Delete confirmation — destructive */}
      {confirmDeleteId && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label="Confirm databank deletion"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
          onClick={() => !deleting && setConfirmDeleteId(null)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-ink/[0.06] bg-white p-5 shadow-2xl dark:border-fog/[0.08] dark:bg-ink"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-50 text-red-600">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                <path d="M12 9v6M12 17h.01M10.3 3.3l-7 12A2 2 0 005 18h14a2 2 0 001.7-3l-7-12a2 2 0 00-3.4 0z" />
              </svg>
            </div>
            <h2 className="mt-3 text-[15px] font-bold text-ink dark:text-fog">
              Delete “{confirmDeleteDb?.name ?? "databank"}”?
            </h2>
            <p className="mt-2 text-[13px] leading-relaxed text-ink/60 dark:text-fog/60">
              All documents, chunks and embeddings inside this databank will be{" "}
              <strong className="font-bold text-red-600">permanently deleted</strong>. Your AI will no longer be able to
              search this knowledge. This cannot be undone.
            </p>
            {confirmDeleteDb && (confirmDeleteDb.doc_count ?? 0) > 0 && (
              <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] font-medium text-amber-700 ring-1 ring-amber-200/50">
                {confirmDeleteDb.doc_count} document{confirmDeleteDb.doc_count === 1 ? "" : "s"} · {formatBytes(confirmDeleteDb.total_size ?? 0)} will be lost.
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setConfirmDeleteId(null)}
                disabled={deleting}
                className="rounded-xl px-4 py-2 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] disabled:opacity-50 dark:text-fog/60"
              >
                Cancel
              </button>
              <button
                onClick={() => void confirmDelete()}
                disabled={deleting}
                className="inline-flex items-center gap-1.5 rounded-xl bg-red-600 px-4 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-red-700 disabled:opacity-50"
              >
                {deleting ? (
                  <>
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    Deleting…
                  </>
                ) : (
                  "Yes, delete databank"
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
