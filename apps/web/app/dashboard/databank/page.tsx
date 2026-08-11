"use client";

import { useState, useEffect, useCallback } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import {
  listDatabanks,
  createDatabank,
  deleteDatabank,
  listDocuments,
  uploadFile,
  scrapeUrl,
  processPending,
  processDocument,
  deleteDocument,
} from "@/lib/api-rag";

type Databank = {
  id: string;
  name: string;
  description?: string;
  accent_color?: string;
  doc_count: number;
  total_size: number;
};

type Document = {
  id: string;
  filename: string;
  file_type: string;
  size: number;
  status: "pending" | "processing" | "completed" | "failed";
  progress?: number;
  stage?: string;
  error?: string;
};

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".xls", ".sql"];
const ACCEPT_MIME = ".pdf,.docx,.txt,.md,.csv,.xlsx,.xls,.sql";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function statusColor(status: string) {
  switch (status) {
    case "completed":
      return "bg-emerald-500";
    case "processing":
      return "bg-deep-violet";
    case "failed":
      return "bg-coral";
    default:
      return "bg-ink/20 dark:bg-fog/20";
  }
}

function statusBadge(status: string) {
  const colors: Record<string, string> = {
    completed: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400",
    processing: "bg-deep-violet/10 text-deep-violet",
    failed: "bg-coral/10 text-coral",
    pending: "bg-ink/[0.04] text-ink/50 dark:bg-fog/[0.04] dark:text-fog/50",
  };
  return colors[status] || colors.pending;
}

const ACCENT_COLORS = [
  { value: "#3d1d6e", label: "Deep Violet" },
  { value: "#b0338a", label: "Magenta" },
  { value: "#ff4f6e", label: "Coral" },
  { value: "#059669", label: "Emerald" },
  { value: "#0284c7", label: "Sky" },
  { value: "#d97706", label: "Amber" },
];

export default function DatabankPage() {
  const [databanks, setDatabanks] = useState<Databank[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newColor, setNewColor] = useState(ACCENT_COLORS[0].value);
  const [scrapeUrlVal, setScrapeUrlVal] = useState("");
  const [crawlMode, setCrawlMode] = useState<"single" | "full">("single");
  const [uploading, setUploading] = useState(false);
  const [scraping, setScraping] = useState(false);
  const [processingAll, setProcessingAll] = useState(false);

  const totalDocs = databanks.reduce((s, d) => s + (d.doc_count || 0), 0);
  const totalSize = databanks.reduce((s, d) => s + (d.total_size || 0), 0);

  const fetchDatabanks = useCallback(async () => {
    try {
      const data = await listDatabanks();
      setDatabanks(Array.isArray(data) ? data : data.databanks || []);
    } catch {
      /* empty */
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchDocuments = useCallback(async (dbId: string) => {
    try {
      const data = await listDocuments(dbId);
      setDocuments(Array.isArray(data) ? data : data.documents || []);
    } catch {
      /* empty */
    }
  }, []);

  useEffect(() => {
    fetchDatabanks();
  }, [fetchDatabanks]);

  useEffect(() => {
    if (selectedId) fetchDocuments(selectedId);
  }, [selectedId, fetchDocuments]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const created = await createDatabank({ name: newName.trim(), description: newDesc.trim() || undefined, accent_color: newColor });
      setDatabanks((prev) => [...prev, created]);
      setShowCreateForm(false);
      setNewName("");
      setNewDesc("");
      setNewColor(ACCENT_COLORS[0].value);
    } catch {
      /* empty */
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await deleteDatabank(id);
      setDatabanks((prev) => prev.filter((d) => d.id !== id));
      if (selectedId === id) {
        setSelectedId(null);
        setDocuments([]);
      }
    } catch {
      /* empty */
    }
  };

  const handleUpload = async (files: FileList | null) => {
    if (!files || !selectedId) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await uploadFile(selectedId, file);
      }
      await fetchDocuments(selectedId);
      await fetchDatabanks();
    } catch {
      /* empty */
    } finally {
      setUploading(false);
    }
  };

  const handleScrape = async () => {
    if (!scrapeUrlVal.trim() || !selectedId) return;
    setScraping(true);
    try {
      await scrapeUrl(selectedId, scrapeUrlVal.trim(), crawlMode);
      setScrapeUrlVal("");
      await fetchDocuments(selectedId);
    } catch {
      /* empty */
    } finally {
      setScraping(false);
    }
  };

  const handleProcessAll = async () => {
    if (!selectedId) return;
    setProcessingAll(true);
    try {
      await processPending(selectedId);
      await fetchDocuments(selectedId);
    } catch {
      /* empty */
    } finally {
      setProcessingAll(false);
    }
  };

  const handleProcessDoc = async (docId: string) => {
    if (!selectedId) return;
    try {
      await processDocument(selectedId, docId);
      await fetchDocuments(selectedId);
    } catch {
      /* empty */
    }
  };

  const handleDeleteDoc = async (docId: string) => {
    if (!selectedId) return;
    try {
      await deleteDocument(selectedId, docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      await fetchDatabanks();
    } catch {
      /* empty */
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    handleUpload(e.dataTransfer.files);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const selectedDatabank = databanks.find((d) => d.id === selectedId);
  const pendingDocs = documents.filter((d) => d.status === "pending" || d.status === "failed");

  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Databank" }]} />
        <div className="mt-2 flex items-center justify-between">
          <div>
            <h1 className="text-[20px] font-bold text-ink dark:text-fog">Databank</h1>
            <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
              Manage knowledge bases and training data for your AI agents.
            </p>
          </div>
          <button
            onClick={() => setShowCreateForm(true)}
            className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
          >
            Create Databank
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
          <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">Total Databanks</p>
          <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{databanks.length}</p>
        </div>
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
          <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">Total Documents</p>
          <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{totalDocs}</p>
        </div>
        <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
          <p className="text-[11px] font-medium text-ink/40 dark:text-fog/40">Total Size</p>
          <p className="mt-1 text-[22px] font-bold text-ink dark:text-fog">{formatBytes(totalSize)}</p>
        </div>
      </div>

      {/* Create form modal */}
      {showCreateForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-md rounded-xl border border-ink/[0.06] bg-white p-5 shadow-xl dark:border-fog/[0.06] dark:bg-ink">
            <h3 className="text-[15px] font-semibold text-ink dark:text-fog">Create Databank</h3>
            <div className="mt-4 space-y-3">
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Name</label>
                <input
                  type="text"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="e.g. Knowledge Base"
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Description (optional)</label>
                <input
                  type="text"
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="What is this databank for?"
                  className="w-full rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium text-ink/60 dark:text-fog/60 mb-1">Accent Color</label>
                <div className="flex gap-2">
                  {ACCENT_COLORS.map((c) => (
                    <button
                      key={c.value}
                      onClick={() => setNewColor(c.value)}
                      className={`h-7 w-7 rounded-full border-2 transition ${
                        newColor === c.value ? "border-ink dark:border-fog scale-110" : "border-transparent"
                      }`}
                      style={{ backgroundColor: c.value }}
                      title={c.label}
                    />
                  ))}
                </div>
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setShowCreateForm(false)}
                className="rounded-lg border border-ink/[0.06] px-4 py-2 text-[12px] font-medium text-ink/60 transition hover:border-ink/[0.1] dark:border-fog/[0.06] dark:text-fog/60"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={!newName.trim() || creating}
                className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
              >
                {creating ? "Creating..." : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Databank cards */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {loading
          ? Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="animate-pulse rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
                <div className="h-4 w-32 rounded bg-ink/[0.06] dark:bg-fog/[0.06]" />
                <div className="mt-2 h-3 w-20 rounded bg-ink/[0.04] dark:bg-fog/[0.04]" />
              </div>
            ))
          : databanks.map((db) => (
              <div
                key={db.id}
                className={`group rounded-xl border bg-white p-4 transition hover:shadow-sm dark:bg-ink ${
                  selectedId === db.id
                    ? "border-deep-violet/30 ring-1 ring-deep-violet/10"
                    : "border-ink/[0.06] hover:border-deep-violet/20 dark:border-fog/[0.06] dark:hover:border-deep-violet/20"
                }`}
              >
                <div className="flex items-start gap-3">
                  <div
                    className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[16px] text-white"
                    style={{ backgroundColor: db.accent_color || "#3d1d6e" }}
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
                      <ellipse cx="12" cy="5" rx="9" ry="3" />
                      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[14px] font-semibold text-ink group-hover:text-deep-violet dark:text-fog truncate">
                      {db.name}
                    </p>
                    <p className="text-[11px] text-ink/40 dark:text-fog/40">
                      {db.doc_count || 0} docs · {formatBytes(db.total_size || 0)}
                    </p>
                    {db.description && (
                      <p className="mt-1 text-[11px] text-ink/35 dark:text-fog/35 line-clamp-1">{db.description}</p>
                    )}
                  </div>
                </div>
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={() => setSelectedId(selectedId === db.id ? null : db.id)}
                    className="flex-1 rounded-lg bg-deep-violet/[0.06] px-3 py-1.5 text-[11px] font-medium text-deep-violet transition hover:bg-deep-violet/10"
                  >
                    {selectedId === db.id ? "Close" : "Enter"}
                  </button>
                  <button
                    onClick={() => handleDelete(db.id)}
                    className="rounded-lg border border-ink/[0.06] px-3 py-1.5 text-[11px] font-medium text-ink/40 transition hover:border-coral/30 hover:text-coral dark:border-fog/[0.06] dark:text-fog/40"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
      </div>

      {/* Expanded databank detail */}
      {selectedDatabank && selectedId && (
        <div className="space-y-4 rounded-xl border border-deep-violet/20 bg-white p-5 dark:bg-ink">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div
                className="flex h-8 w-8 items-center justify-center rounded-lg text-white"
                style={{ backgroundColor: selectedDatabank.accent_color || "#3d1d6e" }}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                  <ellipse cx="12" cy="5" rx="9" ry="3" />
                  <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                </svg>
              </div>
              <div>
                <h2 className="text-[16px] font-bold text-ink dark:text-fog">{selectedDatabank.name}</h2>
                <p className="text-[11px] text-ink/40 dark:text-fog/40">
                  {documents.length} documents · {formatBytes(selectedDatabank.total_size || 0)}
                </p>
              </div>
            </div>
          </div>

          {/* Upload dropzone */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            className={`flex h-28 items-center justify-center rounded-lg border-2 border-dashed transition ${
              uploading
                ? "border-deep-violet/40 bg-deep-violet/[0.02]"
                : "border-ink/[0.12] bg-fog/30 hover:border-deep-violet/30 hover:bg-deep-violet/[0.02] dark:border-fog/[0.12] dark:bg-ink/30 dark:hover:border-deep-violet/30"
            }`}
          >
            <label className="flex cursor-pointer flex-col items-center gap-2">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7 text-ink/20 dark:text-fog/20">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M17 8l-5-5-5 5M12 3v12" />
              </svg>
              <div className="text-center">
                <p className="text-[12px] text-ink/40 dark:text-fog/40">
                  {uploading ? "Uploading..." : <>Drag & drop files here, or <span className="font-medium text-deep-violet">browse</span></>}
                </p>
                <p className="mt-0.5 text-[10px] text-ink/25 dark:text-fog/25">PDF, DOCX, TXT, MD, CSV, XLS, SQL</p>
              </div>
              <input
                type="file"
                multiple
                accept={ACCEPT_MIME}
                onChange={(e) => handleUpload(e.target.files)}
                className="hidden"
              />
            </label>
          </div>

          {/* Scrape form — disabled until scraper is implemented */}
          <div className="rounded-lg border border-ink/[0.06] p-3 opacity-60 dark:border-fog/[0.06]">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Scrape Website</p>
              <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[9px] font-semibold text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">Coming Soon</span>
            </div>
            <p className="text-[11px] text-ink/30 dark:text-fog/30">Web scraping will be available in a future update.</p>
          </div>

          {/* Process All */}
          {pendingDocs.length > 0 && (
            <button
              onClick={handleProcessAll}
              disabled={processingAll}
              className="rounded-lg bg-emerald-500 px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-emerald-600 disabled:opacity-40"
            >
              {processingAll ? "Processing..." : `Process All (${pendingDocs.length})`}
            </button>
          )}

          {/* Documents list */}
          <div>
            <p className="mb-2 text-[12px] font-semibold text-ink/60 dark:text-fog/60">Documents</p>
            {documents.length === 0 ? (
              <p className="text-[12px] text-ink/30 dark:text-fog/30">No documents yet. Upload files or scrape a URL.</p>
            ) : (
              <div className="space-y-1.5">
                {documents.map((doc) => (
                  <div
                    key={doc.id}
                    className="flex items-center gap-3 rounded-lg border border-ink/[0.06] px-3 py-2.5 dark:border-fog/[0.06]"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-[12px] font-medium text-ink dark:text-fog truncate">{doc.filename}</p>
                        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] font-semibold ${statusBadge(doc.status)}`}>
                          {doc.status}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] text-ink/30 dark:text-fog/30">{formatBytes(doc.size)}</span>
                        {doc.stage && (
                          <span className="text-[10px] text-deep-violet">{doc.stage}</span>
                        )}
                      </div>
                      {(doc.status === "processing" || (doc.progress !== undefined && doc.progress > 0)) && (
                        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
                          <div
                            className="h-full rounded-full bg-deep-violet transition-all duration-500"
                            style={{ width: `${doc.progress ?? 0}%` }}
                          />
                        </div>
                      )}
                      {doc.error && (
                        <p className="mt-1 text-[10px] text-coral">{doc.error}</p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-1.5">
                      {(doc.status === "pending" || doc.status === "failed") && (
                        <button
                          onClick={() => handleProcessDoc(doc.id)}
                          className="rounded-md bg-deep-violet/[0.06] px-2.5 py-1 text-[10px] font-medium text-deep-violet transition hover:bg-deep-violet/10"
                        >
                          Process
                        </button>
                      )}
                      <button
                        onClick={() => handleDeleteDoc(doc.id)}
                        className="rounded-md px-2.5 py-1 text-[10px] font-medium text-ink/30 transition hover:text-coral dark:text-fog/30"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
