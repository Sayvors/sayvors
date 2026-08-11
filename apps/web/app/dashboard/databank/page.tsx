"use client";

import { useState, useEffect, useCallback } from "react";
import { listDatabanks, createDatabank, deleteDatabank } from "@/lib/api-rag";
import DatabankStats from "@/components/databank/DatabankStats";
import DatabankCard from "@/components/databank/DatabankCard";
import DatabankTabs from "@/components/databank/DatabankTabs";
import FilesTab from "@/components/databank/FilesTab";
import CrawlerTab from "@/components/databank/CrawlerTab";
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

type DatabankTab = "files" | "crawler";

const STEP_ORDER: ProcessingStep[] = ["sending", "chunking", "vectorizing", "storing", "finalizing", "done"];

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

export default function DatabankPage() {
  const [databanks, setDatabanks] = useState<Databank[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [activeDatabankTab, setActiveDatabankTab] = useState<DatabankTab>("files");

  // Processing panel state
  const [panelOpen, setPanelOpen] = useState(false);
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);

  const totalDocs = databanks.reduce((s, d) => s + (d.doc_count || 0), 0);
  const totalSize = databanks.reduce((s, d) => s + (d.total_size || 0), 0);
  const completedDocs = documents.filter((d) => d.status === "completed");
  const pendingDocs = documents.filter((d) => d.status === "pending" || d.status === "failed");

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

  useEffect(() => {
    fetchDatabanks();
  }, [fetchDatabanks]);

  const simulateProcessing = (filenames: string[]) => {
    const newJobs: ProcessingJob[] = filenames.map((filename, i) => ({
      id: `job-${Date.now()}-${i}`,
      filename,
      currentStep: "sending",
      progress: 0,
    }));

    setJobs((prev) => [...prev, ...newJobs]);

    for (const job of newJobs) {
      let stepIndex = 0;

      const interval = setInterval(() => {
        setJobs((prev) =>
          prev.map((j) => {
            if (j.id !== job.id) return j;

            const newProgress = j.progress + Math.random() * 15 + 5;
            if (newProgress >= 100) {
              stepIndex++;
              if (stepIndex < STEP_ORDER.length) {
                return { ...j, currentStep: STEP_ORDER[stepIndex], progress: 0 };
              } else {
                clearInterval(interval);
                return { ...j, currentStep: "done", progress: 100 };
              }
            }
            return { ...j, progress: newProgress };
          })
        );
      }, 800);
    }
  };

  const handleCreate = async (name: string, description: string) => {
    setCreating(true);
    try {
      const created = await createDatabank({ name, description: description || undefined });
      setDatabanks((prev) => [...prev, created]);
      setShowCreateForm(false);
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

  const handleUpload = (files: FileList | null) => {
    if (!files) return;
    const newDocs: Document[] = Array.from(files).map((file, i) => ({
      id: `local-${Date.now()}-${i}`,
      filename: file.name,
      file_type: file.type,
      size: file.size,
      status: "pending" as const,
    }));
    setDocuments((prev) => [...prev, ...newDocs]);
  };

  const handleCrawl = (url: string, mode: "single" | "full") => {
    const newDoc: Document = {
      id: `local-${Date.now()}`,
      filename: url,
      file_type: "url",
      size: 0,
      status: "pending",
    };
    setDocuments((prev) => [...prev, newDoc]);
  };

  const handleProcessAll = () => {
    const pendingDocs = documents.filter((d) => d.status === "pending" || d.status === "failed");
    const filenames = pendingDocs.map((d) => d.filename);
    if (filenames.length === 0) return;
    setDocuments((prev) =>
      prev.map((d) =>
        d.status === "pending" || d.status === "failed"
          ? { ...d, status: "processing" as const, progress: 0 }
          : d
      )
    );
    simulateProcessing(filenames);
  };

  const handleProcessDoc = (docId: string) => {
    const doc = documents.find((d) => d.id === docId);
    if (!doc) return;
    setDocuments((prev) =>
      prev.map((d) => (d.id === docId ? { ...d, status: "processing" as const, progress: 0 } : d))
    );
    simulateProcessing([doc.filename]);
  };

  const handleDeleteDoc = (docId: string) => {
    setDocuments((prev) => prev.filter((d) => d.id !== docId));
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
              Knowledge base for your AI agents. Upload files, crawl websites, and train your agents.
            </p>
          </div>
          <button
            onClick={() => setShowCreateForm(true)}
            className="rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-[0.98]"
          >
            + Create Databank
          </button>
        </div>

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
                <FilesTab
                  documents={documents}
                  pendingCount={pendingDocs.length}
                  onUpload={handleUpload}
                  onProcessAll={handleProcessAll}
                  onProcessDoc={handleProcessDoc}
                  onDeleteDoc={handleDeleteDoc}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  formatBytes={formatBytes}
                />
              )}

              {activeDatabankTab === "crawler" && (
                <CrawlerTab onCrawl={handleCrawl} />
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
              Databanks store knowledge for your AI agents. Upload PDFs, crawl websites, or add text to train your agents.
            </p>
            <button
              onClick={() => setShowCreateForm(true)}
              className="mt-4 rounded-xl bg-deep-violet px-6 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90"
            >
              + Create Databank
            </button>
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
