"use client";

import Link from "next/link";
import { useEffect, useState, Fragment } from "react";
import {
  listDatabanks,
  deleteDatabank,
  listDocuments,
  retryDocuments,
  processPending,
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
  if (status === "ready" || status === "completed" || status === "processed") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        Ready
      </span>
    );
  }
  if (status === "processing") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
        Processing
      </span>
    );
  }
  if (status === "pending" || status === "queued") {
    return (
      <span
        title="File uploaded but not yet parsed into searchable chunks. Click Process to start."
        className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold text-blue-700"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-blue-500" />
        Waiting to process
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold text-red-600">
        <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
        Failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-ink/5 px-2 py-0.5 text-[10px] font-medium text-ink/40">
      {status || "Unknown"}
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

  useEffect(() => {
    async function load() {
      try {
        const data = await listDatabanks();
        const list = Array.isArray(data) ? data : data?.databanks ?? [];
        setDatabanks(list);
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

  async function handleDelete(id: string) {
    try {
      await deleteDatabank(id);
      setDatabanks((prev) => prev.filter((db) => db.id !== id));
      if (selectedId === id) setSelectedId(null);
    } catch {
      // silent
    }
  }

  async function refreshDocs() {
    if (!selectedId) return;
    try {
      const data = await listDocuments(selectedId);
      setDocs(Array.isArray(data) ? data : data?.documents ?? []);
    } catch {
      // silent
    }
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

  const stuckCount = docs.filter(
    (d) =>
      d.status === "pending" ||
      d.status === "queued" ||
      d.status === "processing" ||
      d.status === "failed"
  ).length;

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
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="space-y-5 p-4 sm:p-6">
        {/* Header */}
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div>
            <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">
              Databanks
            </h1>
            <p className="mt-0.5 text-[12px] text-ink/65 sm:text-[13px]">
              Knowledge stores for your AI agents and workflows.
            </p>
          </div>
          <Link
            href="/dashboard/databank/new"
            className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-[0.98]"
          >
            + Create Databank
          </Link>
        </div>

        {/* Databank Cards */}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {loading
            ? Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="animate-pulse rounded-2xl border-2 border-white bg-white/80 p-4"
                >
                  <div className="h-4 w-24 rounded-lg bg-ink/[0.06]" />
                  <div className="mt-3 h-3 w-16 rounded-lg bg-ink/[0.04]" />
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
                      "group cursor-pointer rounded-2xl border-2 p-4 text-left transition",
                      isSelected
                        ? "border-deep-violet bg-white shadow-md"
                        : "border-white bg-white/80 hover:border-deep-violet/20 hover:shadow-sm",
                    ].join(" ")}
                  >
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <div
                        className="flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-md"
                        style={{ backgroundColor: db.accent_color || "#3d1d6e" }}
                      >
                        <svg
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.5"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className="h-5 w-5"
                        >
                          <ellipse cx="12" cy="5" rx="9" ry="3" />
                          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                        </svg>
                      </div>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          void handleDelete(db.id);
                        }}
                        className="rounded-lg border border-ink/10 px-2 py-1 text-[10px] font-semibold text-ink/50 opacity-0 transition hover:text-coral group-hover:opacity-100"
                      >
                        Delete
                      </button>
                    </div>
                    <div className="text-[14px] font-bold text-ink">
                      {db.name}
                    </div>
                    <div className="mt-1 text-[11px] text-ink/50">
                      {db.description || "No description"}
                    </div>
                    <div className="mt-4 flex items-center justify-between text-[11px] text-ink/55">
                      <span>{db.doc_count ?? 0} docs</span>
                      <span>{formatBytes(db.total_size ?? 0)}</span>
                    </div>
                  </div>
                );
              })}
        </div>

        {!loading && databanks.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-ink/10 bg-white/60 px-6 py-16 text-center">
            <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-deep-violet/10">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-10 w-10 text-deep-violet"
              >
                <ellipse cx="12" cy="5" rx="9" ry="3" />
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
              </svg>
            </div>
            <h2 className="mt-4 text-[18px] font-bold text-ink">
              Create your first databank
            </h2>
            <p className="mt-2 max-w-sm text-[13px] text-ink/50">
              Start by uploading files, crawling a site, or creating a blank
              knowledge base.
            </p>
            <Link
              href="/dashboard/databank/new"
              className="mt-4 rounded-xl bg-deep-violet px-6 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90"
            >
              + Create Databank
            </Link>
          </div>
        )}

        {/* Selected databank detail */}
        {selected && (
          <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">
                  Selected databank
                </p>
                <h2 className="mt-1 text-[20px] font-bold text-ink">
                  {selected.name}
                </h2>
                {selected.description && (
                  <p className="mt-0.5 text-[12px] text-ink/50">
                    {selected.description}
                  </p>
                )}
              </div>
              <Link
                href="/dashboard/databank/new"
                className="inline-flex items-center gap-1.5 rounded-xl border border-ink/10 bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02]"
              >
                <svg
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  className="h-3.5 w-3.5"
                >
                  <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                </svg>
                Add source
              </Link>
            </div>

            {/* Stats row */}
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-ink/[0.02] p-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">
                  Documents
                </div>
                <div className="mt-2 text-[22px] font-bold text-ink">
                  {selected.doc_count ?? docs.length}
                </div>
              </div>
              <div className="rounded-2xl bg-ink/[0.02] p-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">
                  Total Size
                </div>
                <div className="mt-2 text-[22px] font-bold text-ink">
                  {formatBytes(selected.total_size ?? 0)}
                </div>
              </div>
              <div className="rounded-2xl bg-ink/[0.02] p-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">
                  AI Search
                </div>
                <div className="mt-2 text-[14px] font-bold text-emerald-600">
                  {docs.some(
                    (d) => d.status === "completed" || d.status === "ready"
                  )
                    ? "Active"
                    : docsLoading
                      ? "…"
                      : "No data"}
                </div>
              </div>
            </div>

            {/* Documents section */}
            <div className="mt-6">
              <div className="flex items-center justify-between">
                <h3 className="text-[14px] font-bold text-ink">Documents</h3>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-ink/40">
                    {docs.length} file{docs.length !== 1 ? "s" : ""}
                  </span>
                  {stuckCount > 0 && (
                    <button
                      type="button"
                      onClick={() => void handleRetryAll()}
                      disabled={processing === "all"}
                      title="Re-queue stuck or failed files without deleting anything"
                      className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
                    >
                      {processing === "all"
                        ? "Retrying…"
                        : `Retry ${stuckCount} file${stuckCount !== 1 ? "s" : ""}`}
                    </button>
                  )}
                </div>
              </div>

              {docsLoading ? (
                <div className="mt-3 space-y-2">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <div
                      key={i}
                      className="h-12 animate-pulse rounded-xl bg-ink/[0.04]"
                    />
                  ))}
                </div>
              ) : docs.length === 0 ? (
                <div className="mt-3 flex flex-col items-center rounded-2xl border border-dashed border-ink/10 bg-ink/[0.01] py-8 text-center">
                  <svg
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    className="h-8 w-8 text-ink/20"
                  >
                    <path
                      d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M14 2v6h6M12 18v-6M9 15h6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                  <p className="mt-2 text-[13px] font-medium text-ink/40">
                    No documents yet
                  </p>
                  <p className="mt-1 text-[11px] text-ink/30">
                    Upload a CSV, PDF, or text file to get started.
                  </p>
                  <Link
                    href="/dashboard/databank/new"
                    className="mt-3 rounded-lg bg-deep-violet/10 px-4 py-1.5 text-[11px] font-semibold text-deep-violet transition hover:bg-deep-violet/20"
                  >
                    Add source
                  </Link>
                </div>
              ) : (
                <div className="mt-3 overflow-x-auto rounded-xl border border-ink/[0.06]">
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr className="border-b border-ink/[0.06] bg-ink/[0.02]">
                        <th className="px-4 py-2.5 text-left font-semibold text-ink/50">
                          File
                        </th>
                        <th className="px-4 py-2.5 text-left font-semibold text-ink/50">
                          Type
                        </th>
                        <th className="px-4 py-2.5 text-left font-semibold text-ink/50">
                          Size
                        </th>
                        <th className="px-4 py-2.5 text-left font-semibold text-ink/50">
                          Status
                        </th>
                        <th className="px-4 py-2.5 text-right font-semibold text-ink/50">
                          Action
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {docs.map((doc) => (
                        <Fragment key={doc.id}>
                          <tr
                            className="border-b border-ink/[0.03] transition hover:bg-ink/[0.01]"
                          >
                            <td className="max-w-[250px] truncate px-4 py-2.5 font-medium text-ink/70">
                              {doc.filename || doc.name || doc.id}
                            </td>
                            <td className="px-4 py-2.5">
                              <span className="inline-block rounded bg-ink/[0.04] px-1.5 py-0.5 text-[10px] font-medium uppercase text-ink/50">
                                {doc.file_type || "—"}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-ink/50">
                              {formatBytes(doc.file_size ?? 0)}
                            </td>
                            <td className="px-4 py-2.5">
                              <StatusBadge status={doc.status} />
                            </td>
                            <td className="px-4 py-2.5 text-right">
                              <div className="flex items-center justify-end gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => togglePreview(doc.id)}
                                  title="View actual uploaded content"
                                  className="rounded-lg border border-ink/10 bg-white px-2.5 py-1 text-[10px] font-semibold text-ink/60 transition hover:bg-ink/[0.04]"
                                >
                                  {previewDocId === doc.id ? "Hide" : "View"}
                                </button>
                                {(doc.status === "pending" ||
                                  doc.status === "queued" ||
                                  doc.status === "processing" ||
                                  doc.status === "failed") && (
                                  <button
                                    type="button"
                                    onClick={() => void handleRetryDoc(doc.id)}
                                    disabled={processing === doc.id}
                                    title="Re-queue this file for processing"
                                    className="rounded-lg border border-deep-violet/20 bg-deep-violet/5 px-2.5 py-1 text-[10px] font-semibold text-deep-violet transition hover:bg-deep-violet/10 disabled:opacity-50"
                                  >
                                    {processing === doc.id ? "…" : "Retry"}
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {previewDocId === doc.id && (
                            <tr key={`${doc.id}-preview`} className="border-b border-ink/[0.06] bg-ink/[0.015]">
                              <td colSpan={5} className="px-4 py-3">
                                {previewLoading ? (
                                  <div className="space-y-1.5">
                                    {Array.from({ length: 4 }).map((_, i) => (
                                      <div key={i} className="h-7 animate-pulse rounded-lg bg-ink/[0.05]" />
                                    ))}
                                  </div>
                                ) : !preview ? (
                                  <p className="text-[12px] text-ink/40">Could not load content.</p>
                                ) : preview.kind === "table" ? (
                                  <div>
                                    <p className="mb-2 text-[11px] font-semibold text-ink/50">
                                      {preview.total} rows · {preview.columns?.length ?? 0} columns
                                    </p>
                                    <div className="overflow-x-auto rounded-xl border border-ink/[0.08] bg-white">
                                      <table className="w-full text-[12px]">
                                        <thead>
                                          <tr className="border-b border-ink/[0.08] bg-ink/[0.03]">
                                            {(preview.columns ?? []).map((col) => (
                                              <th key={col} className="whitespace-nowrap px-3 py-2 text-left font-semibold text-ink/60">
                                                {col}
                                              </th>
                                            ))}
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {(preview.rows ?? []).map((row, ri) => (
                                            <tr key={ri} className="border-b border-ink/[0.04] last:border-0 hover:bg-ink/[0.015]">
                                              {(preview.columns ?? []).map((col) => (
                                                <td key={col} className="max-w-[220px] truncate px-3 py-1.5 text-ink/70">
                                                  {row[col] ?? ""}
                                                </td>
                                              ))}
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                    {preview.total > preview.page_size && (
                                      <div className="mt-2 flex items-center justify-center gap-2 text-[11px]">
                                        <button
                                          type="button"
                                          disabled={previewPage <= 1 || previewLoading}
                                          onClick={() => void loadPreview(doc.id, previewPage - 1)}
                                          className="rounded-lg border border-ink/10 px-3 py-1 font-medium text-ink/60 transition hover:bg-ink/[0.03] disabled:opacity-30"
                                        >
                                          Prev
                                        </button>
                                        <span className="text-ink/45">
                                          Page {previewPage} of {Math.ceil(preview.total / preview.page_size)}
                                        </span>
                                        <button
                                          type="button"
                                          disabled={previewPage >= Math.ceil(preview.total / preview.page_size) || previewLoading}
                                          onClick={() => void loadPreview(doc.id, previewPage + 1)}
                                          className="rounded-lg border border-ink/10 px-3 py-1 font-medium text-ink/60 transition hover:bg-ink/[0.03] disabled:opacity-30"
                                        >
                                          Next
                                        </button>
                                      </div>
                                    )}
                                  </div>
                                ) : (
                                  <div>
                                    <p className="mb-2 text-[11px] font-semibold text-ink/50">
                                      {preview.total} stored chunks (what the AI searches)
                                    </p>
                                    <div className="space-y-1.5">
                                      {(preview.chunks ?? []).map((c, i) => (
                                        <p key={i} className="rounded-lg bg-white px-3 py-2 text-[12px] leading-relaxed text-ink/65">
                                          {c}
                                        </p>
                                      ))}
                                      {(preview.chunks ?? []).length === 0 && (
                                        <p className="text-[12px] text-ink/40">No parsed content yet — file may still be processing.</p>
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
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
