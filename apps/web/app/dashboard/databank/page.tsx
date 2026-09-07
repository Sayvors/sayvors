"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  listDatabanks,
  createDatabank,
  deleteDatabank,
  listDocuments,
  uploadFile,
  deleteDocument,
  processPending,
  processDocument,
  listJobs,
  scrapeUrl,
} from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import DatabankStats from "@/components/databank/DatabankStats";
import DatabankCard from "@/components/databank/DatabankCard";
import DatabankTabs, { type DatabankTab } from "@/components/databank/DatabankTabs";
import FilesTab from "@/components/databank/FilesTab";
import CrawlerTab from "@/components/databank/CrawlerTab";
import DatabaseTab from "@/components/databank/DatabaseTab";
import RetrievalTab from "@/components/databank/RetrievalTab";
import ProcessingPanel, { type ProcessingJob, type ProcessingStep } from "@/components/databank/ProcessingPanel";
import CreateDatabankModal from "@/components/databank/CreateDatabankModal";

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

function formatBytes(bytes: number): string {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function jobToPanelJob(j: {
  id: string;
  job_type: string;
  status: string;
  progress: number;
  stage?: string | null;
}): ProcessingJob {
  const step: ProcessingStep =
    j.status === "completed" || j.status === "failed"
      ? "done"
      : j.stage?.toLowerCase().includes("chunk")
        ? "chunking"
        : j.stage?.toLowerCase().includes("embed")
          ? "vectorizing"
          : j.stage?.toLowerCase().includes("pars")
            ? "sending"
            : j.progress >= 90
              ? "finalizing"
              : j.progress >= 50
                ? "vectorizing"
                : j.progress > 0
                  ? "chunking"
                  : "sending";
  return {
    id: j.id,
    filename: j.stage || `${j.job_type} job`,
    currentStep: step,
    progress: j.status === "completed" ? 100 : j.progress,
  };
}

export default function DatabankPage() {
  const [databanks, setDatabanks] = useState<Databank[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [activeDatabankTab, setActiveDatabankTab] = useState<DatabankTab>("files");
  const [notice, setNotice] = useState<string | null>(null);

  // Processing panel state (fed by real ingest jobs)
  const [panelOpen, setPanelOpen] = useState(false);
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const totalDocs = databanks.reduce((s, d) => s + (d.doc_count || 0), 0);
  const totalSize = databanks.reduce((s, d) => s + (d.total_size || 0), 0);
  const completedDocs = documents.filter((d) => d.status === "completed");
  const pendingDocs = documents.filter((d) => d.status === "pending" || d.status === "failed");

  const fetchDatabanks = useCallback(async () => {
    try {
      const data = await listDatabanks();
      const banks = Array.isArray(data) ? data : data.databanks || [];
      setDatabanks(
        banks.map((b: Databank & { doc_count?: number; total_size?: number }) => ({
          ...b,
          doc_count: b.doc_count ?? 0,
          total_size: b.total_size ?? 0,
        }))
      );
    } catch {
      /* backend down — empty state renders */
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchDocuments = useCallback(async (bankId: string) => {
    setDocsLoading(true);
    try {
      const data = await listDocuments(bankId);
      setDocuments(
        (data.documents ?? []).map((d: {
          id: string; filename: string; file_type: string; size_bytes: number;
          status: string; chunk_count: number;
        }) => ({
          id: d.id,
          filename: d.filename,
          file_type: d.file_type,
          size: d.size_bytes ?? 0,
          status: (["pending", "processing", "completed", "failed"] as const).includes(d.status as Document["status"])
            ? (d.status as Document["status"])
            : "pending",
        }))
      );
    } catch {
      setDocuments([]);
    } finally {
      setDocsLoading(false);
    }
  }, []);

  const refreshJobs = useCallback(async () => {
    try {
      const data = await listJobs();
      const mapped = ((data.jobs ?? []) as {
        id: string; job_type: string; status: string; progress: number; stage?: string | null;
      }[]).slice(0, 10).map(jobToPanelJob);
      setJobs(mapped);
      return mapped.some((j) => j.currentStep !== "done");
    } catch {
      return false;
    }
  }, []);

  // Poll jobs + documents while anything is still working.
  useEffect(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (!selectedId) return;
    pollRef.current = setInterval(async () => {
      const active = await refreshJobs();
      await fetchDocuments(selectedId);
      await fetchDatabanks();
      if (!active && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, 4000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [selectedId, fetchDocuments, fetchDatabanks, refreshJobs]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load from API on mount
    fetchDatabanks();
    refreshJobs();
  }, [fetchDatabanks, refreshJobs]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load docs on select, clear on deselect
    if (selectedId) fetchDocuments(selectedId);
    else setDocuments([]);
  }, [selectedId, fetchDocuments]);

  function flash(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice((n) => (n === message ? null : n)), 5000);
  }

  const handleCreate = async (
    name: string,
    description: string,
    sourceType: "files" | "crawler" | "database" | "empty",
    sourceConfig: { files?: File[]; crawlerUrl?: string; crawlerDepth?: number }
  ) => {
    setCreating(true);
    try {
      const created = await createDatabank({ name, description: description || undefined });
      setDatabanks((prev) => [...prev, { ...created, doc_count: 0, total_size: 0 }]);
      setShowCreateForm(false);
      setSelectedId(created.id);

      if (sourceType === "files" && sourceConfig.files?.length) {
        setActiveDatabankTab("files");
        await handleUploadFiles(created.id, sourceConfig.files);
      } else if (sourceType === "crawler" && sourceConfig.crawlerUrl) {
        setActiveDatabankTab("crawler");
        await scrapeUrl(created.id, sourceConfig.crawlerUrl, "single");
        flash("Crawl queued — pages will appear as documents shortly.");
      } else if (sourceType === "database") {
        setActiveDatabankTab("database");
      } else {
        setActiveDatabankTab("files");
      }
      await fetchDatabanks();
    } catch {
      flash("Could not create databank. Is the backend running?");
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
      flash("Could not delete databank.");
    }
  };

  const handleUploadFiles = async (bankId: string, files: File[] | FileList) => {
    const list = Array.from(files);
    if (list.length === 0) return;
    setUploading(true);
    try {
      for (const file of list) {
        await uploadFile(bankId, file);
      }
      await fetchDocuments(bankId);
      await fetchDatabanks();
      setPanelOpen(true);
      await refreshJobs();
      flash(`${list.length} file(s) uploaded — press Process All to embed.`);
    } catch (e) {
      flash(e instanceof Error ? e.message.slice(0, 160) : "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleUpload = (files: FileList | null) => {
    if (!files || !selectedId) return;
    void handleUploadFiles(selectedId, files);
  };

  const handleCrawl = async (url: string, mode: "single" | "full") => {
    if (!selectedId) return;
    try {
      await scrapeUrl(selectedId, url, mode);
      setPanelOpen(true);
      flash(`Crawl queued for ${url} — pages will appear as documents shortly.`);
    } catch (e) {
      flash(e instanceof Error ? e.message.slice(0, 160) : "Crawl failed to start.");
    }
  };

  const handleProcessAll = async () => {
    if (!selectedId || pendingDocs.length === 0) return;
    try {
      await processPending(selectedId);
      setPanelOpen(true);
      await refreshJobs();
    } catch (e) {
      flash(e instanceof Error ? e.message.slice(0, 160) : "Nothing to process.");
    }
  };

  const handleProcessDoc = async (docId: string) => {
    try {
      await processDocument(selectedId ?? "", docId);
      setPanelOpen(true);
      await refreshJobs();
    } catch (e) {
      flash(e instanceof Error ? e.message.slice(0, 160) : "Could not start processing.");
    }
  };

  const handleDeleteDoc = async (docId: string) => {
    if (!selectedId) return;
    try {
      await deleteDocument(selectedId, docId);
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      await fetchDatabanks();
    } catch {
      flash("Could not delete document.");
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

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="p-4 sm:p-6 space-y-5">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-[20px] sm:text-[22px] font-bold text-ink">Databank</h1>
            <p className="mt-0.5 text-[12px] sm:text-[13px] text-ink/65">
              Knowledge base for your AI agents. Upload files, crawl websites, connect live databases.
            </p>
          </div>
          <button
            onClick={() => setShowCreateForm(true)}
            className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-[0.98]"
          >
            + Create Databank
          </button>
        </div>

        {notice && (
          <div role="status" className="rounded-xl border border-deep-violet/20 bg-white px-4 py-2.5 text-[12px] font-medium text-ink/70">
            {notice}
          </div>
        )}

        {/* Stats */}
        <DatabankStats
          totalDatabanks={databanks.length}
          totalDocs={totalDocs}
          totalSize={formatBytes(totalSize)}
          processedCount={completedDocs.length}
        />

        {/* Databank Cards */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {loading
            ? Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="animate-pulse rounded-2xl border-2 border-white bg-white/80 p-4">
                  <div className="h-4 w-32 rounded-lg bg-ink/[0.06]" />
                  <div className="mt-2 h-3 w-20 rounded-lg bg-ink/[0.04]" />
                </div>
              ))
            : databanks.map((db) => (
                <DatabankCard
                  key={db.id}
                  id={db.id}
                  name={db.name}
                  description={db.description}
                  accentColor={db.accent_color}
                  docCount={db.doc_count}
                  totalSize={db.total_size}
                  isSelected={selectedId === db.id}
                  onSelect={() => setSelectedId(selectedId === db.id ? null : db.id)}
                  onDelete={() => handleDelete(db.id)}
                  formatBytes={formatBytes}
                />
              ))}
        </div>

        {/* Expanded Databank Detail */}
        {selectedDatabank && selectedId && (
          <div className="rounded-2xl border-2 border-deep-violet/20 bg-white/80 overflow-hidden">
            {/* Databank Header */}
            <div className="flex items-center gap-3 px-5 py-4 border-b border-deep-violet/10">
              <div
                className="flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-md"
                style={{ backgroundColor: selectedDatabank.accent_color || "#3d1d6e" }}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6">
                  <ellipse cx="12" cy="5" rx="9" ry="3" />
                  <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                </svg>
              </div>
              <div className="flex-1">
                <h2 className="text-[16px] font-bold text-ink">{selectedDatabank.name}</h2>
                <p className="text-[11px] text-ink/45">
                  {documents.length} documents · {formatBytes(selectedDatabank.total_size || 0)}
                </p>
              </div>
              <button
                onClick={() => handleDelete(selectedDatabank.id)}
                className="rounded-lg border-2 border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/50 transition hover:border-coral/30 hover:text-coral"
              >
                Delete
              </button>
            </div>

            {/* Tabs */}
            <DatabankTabs activeTab={activeDatabankTab} onTabChange={setActiveDatabankTab} />

            {/* Tab Content */}
            <div className="p-5">
              {activeDatabankTab === "files" && (
                docsLoading ? (
                  <div className="flex justify-center py-10" aria-hidden>
                    <LogoLoader size={36} />
                  </div>
                ) : (
                  <FilesTab
                    documents={documents}
                    pendingCount={pendingDocs.length}
                    onUpload={handleUpload}
                    onProcessAll={() => void handleProcessAll()}
                    onProcessDoc={(id) => void handleProcessDoc(id)}
                    onDeleteDoc={(id) => void handleDeleteDoc(id)}
                    onDrop={handleDrop}
                    onDragOver={handleDragOver}
                    formatBytes={formatBytes}
                  />
                )
              )}

              {activeDatabankTab === "crawler" && (
                <CrawlerTab onCrawl={(url, mode) => void handleCrawl(url, mode)} />
              )}

              {activeDatabankTab === "database" && (
                <DatabaseTab
                  databankId={selectedId}
                  onIngested={() => {
                    void fetchDocuments(selectedId);
                    void fetchDatabanks();
                    void refreshJobs();
                    setPanelOpen(true);
                  }}
                />
              )}

              {activeDatabankTab === "retrieval" && (
                <RetrievalTab databankId={selectedId} />
              )}
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && databanks.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-deep-violet/10">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-10 w-10 text-deep-violet">
                <ellipse cx="12" cy="5" rx="9" ry="3" />
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
              </svg>
            </div>
            <h2 className="mt-4 text-[18px] font-bold text-ink">Create your first Databank</h2>
            <p className="mt-2 text-[13px] text-ink/50 max-w-sm">
              Databanks store knowledge for your AI agents. Upload PDFs, crawl websites, connect a live database, or test retrieval accuracy.
            </p>
            <button
              onClick={() => setShowCreateForm(true)}
              className="mt-4 rounded-xl bg-deep-violet px-6 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90"
            >
              + Create Databank
            </button>
          </div>
        )}

        {uploading && (
          <div className="fixed bottom-6 left-6 z-50 flex items-center gap-2 rounded-full bg-ink px-4 py-2.5 text-[12px] font-semibold text-white shadow-lg">
            <LogoLoader size={18} /> Uploading files…
          </div>
        )}
      </div>

      {/* Modals */}
      <CreateDatabankModal
        isOpen={showCreateForm}
        onClose={() => setShowCreateForm(false)}
        onCreate={handleCreate}
        creating={creating}
      />

      <ProcessingPanel
        jobs={jobs}
        isOpen={panelOpen}
        onToggle={() => setPanelOpen(!panelOpen)}
        onClose={() => {
          setPanelOpen(false);
          setJobs((prev) => prev.filter((j) => j.currentStep !== "done"));
        }}
      />
    </div>
  );
}
