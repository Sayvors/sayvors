"use client";

import { useState, useEffect } from "react";

type SourceType = "files" | "crawler" | "database" | "empty";

interface CreateDatabankModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreate: (name: string, description: string, sourceType: SourceType, sourceConfig: SourceConfig) => void;
  creating: boolean;
}

export interface SourceConfig {
  files?: File[];
  crawlerUrl?: string;
  crawlerDepth?: number;
}

const STEPS = [
  { id: 1, label: "Details" },
  { id: 2, label: "Source" },
  { id: 3, label: "Configure" },
  { id: 4, label: "Review" },
];

export default function CreateDatabankModal({ isOpen, onClose, onCreate, creating }: CreateDatabankModalProps) {
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [sourceType, setSourceType] = useState<SourceType | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [crawlerUrl, setCrawlerUrl] = useState("");
  const [crawlerDepth, setCrawlerDepth] = useState(2);

  // Reset state when modal opens/closes
  useEffect(() => {
    if (isOpen) {
      setStep(1);
      setName("");
      setDesc("");
      setSourceType(null);
      setFiles([]);
      setCrawlerUrl("");
      setCrawlerDepth(2);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const canProceed = () => {
    if (step === 1) return name.trim().length > 0;
    if (step === 2) return sourceType !== null;
    if (step === 3) {
      if (sourceType === "files") return files.length > 0;
      if (sourceType === "crawler") return crawlerUrl.trim().length > 0;
      return true;
    }
    return true;
  };

  const handleNext = () => {
    if (canProceed() && step < STEPS.length) setStep(step + 1);
  };

  const handleBack = () => {
    if (step > 1) setStep(step - 1);
  };

  const handleCreate = () => {
    if (!sourceType) return;
    onCreate(name.trim(), desc.trim(), sourceType, {
      files: sourceType === "files" ? files : undefined,
      crawlerUrl: sourceType === "crawler" ? crawlerUrl : undefined,
      crawlerDepth: sourceType === "crawler" ? crawlerDepth : undefined,
    });
  };

  const stepClass = (n: number) => {
    const active = step === n;
    const done = step > n;
    const reachable = done || active;
    return [
      "flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-semibold transition-all",
      active && "bg-deep-violet text-white shadow-sm",
      done && "bg-deep-violet/10 text-deep-violet",
      !reachable && "bg-ink/[0.04] text-ink/40",
    ].filter(Boolean).join(" ");
  };

  const connectorClass = (n: number) =>
    `h-px flex-1 transition-colors ${step > n ? "bg-deep-violet/30" : "bg-ink/10"}`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-lg mx-4 rounded-2xl border-2 border-white bg-white p-5 shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-[16px] font-bold text-ink">Create Databank</h3>
            <p className="text-[12px] text-ink/50 mt-0.5">Set up a new knowledge base for your agents</p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-ink/40 transition hover:bg-ink/[0.05] hover:text-ink/70"
            aria-label="Close"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Internal breadcrumb stepper */}
        <nav className="mt-4 flex items-center gap-2" aria-label="Creation progress">
          {STEPS.map((s, i) => (
            <div key={s.id} className="flex flex-1 items-center gap-2 last:flex-none">
              <button
                type="button"
                onClick={() => (step > s.id ? setStep(s.id) : undefined)}
                disabled={step <= s.id}
                className={stepClass(s.id) + " disabled:cursor-default"}
              >
                <span className={`flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-bold ${
                  step === s.id ? "bg-white/20" : step > s.id ? "bg-deep-violet/20" : "bg-ink/10"
                }`}>
                  {step > s.id ? "✓" : s.id}
                </span>
                <span className="hidden sm:inline">{s.label}</span>
              </button>
              {i < STEPS.length - 1 && <div className={connectorClass(s.id)} />}
            </div>
          ))}
        </nav>

        {/* Step content */}
        <div className="mt-5 min-h-[180px]">
          {step === 1 && (
            <div className="space-y-3">
              <div>
                <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g., Product Knowledge Base"
                  className="w-full rounded-xl border-2 border-white bg-ink/[0.03] px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40"
                />
              </div>
              <div>
                <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">Description (optional)</label>
                <input
                  type="text"
                  value={desc}
                  onChange={(e) => setDesc(e.target.value)}
                  placeholder="What is this databank for?"
                  className="w-full rounded-xl border-2 border-white bg-ink/[0.03] px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40"
                />
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-2">
              <p className="text-[11px] text-ink/50">Choose how to populate this databank.</p>
              {[
                { v: "files" as const, t: "Upload files", d: "PDF, TXT, DOCX — up to 50MB each" },
                { v: "crawler" as const, t: "Web crawler", d: "Scrape a website by URL" },
                { v: "database" as const, t: "Live database", d: "PostgreSQL or MySQL — query & ingest" },
                { v: "empty" as const, t: "Start empty", d: "Add sources later from the databank page" },
              ].map((opt) => {
                const selected = sourceType === opt.v;
                return (
                  <button
                    key={opt.v}
                    type="button"
                    onClick={() => setSourceType(opt.v)}
                    className={`flex w-full items-start gap-3 rounded-xl border-2 p-3 text-left transition ${
                      selected ? "border-deep-violet/50 bg-deep-violet/[0.04]" : "border-white bg-ink/[0.03] hover:border-ink/10"
                    }`}
                  >
                    <span className={`mt-0.5 flex h-4 w-4 items-center justify-center rounded-full border-2 ${
                      selected ? "border-deep-violet bg-deep-violet" : "border-ink/20"
                    }`}>
                      {selected && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
                    </span>
                    <span>
                      <span className="block text-[13px] font-semibold text-ink">{opt.t}</span>
                      <span className="block text-[11px] text-ink/50">{opt.d}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          {step === 3 && (
            <div className="space-y-3">
              {sourceType === "files" && (
                <div>
                  <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">Files</label>
                  <label className="block cursor-pointer rounded-xl border-2 border-dashed border-ink/15 bg-ink/[0.03] p-4 text-center transition hover:border-deep-violet/40">
                    <p className="text-[12px] font-semibold text-ink/60">Drop files here or click to browse</p>
                    <p className="mt-1 text-[10px] text-ink/40">
                      {files.length === 0 ? "PDF, DOCX, TXT, MD, CSV, XLSX, SQL" : `${files.length} file(s) selected`}
                    </p>
                    <input
                      type="file"
                      multiple
                      accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.xls,.sql"
                      onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                      className="hidden"
                    />
                  </label>
                  {files.length > 0 && (
                    <ul className="mt-2 max-h-24 space-y-1 overflow-y-auto">
                      {files.map((f) => (
                        <li key={`${f.name}-${f.size}`} className="truncate text-[11px] text-ink/55">
                          {f.name}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {sourceType === "crawler" && (
                <>
                  <div>
                    <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">Website URL</label>
                    <input
                      type="url"
                      value={crawlerUrl}
                      onChange={(e) => setCrawlerUrl(e.target.value)}
                      placeholder="https://example.com/docs"
                      className="w-full rounded-xl border-2 border-white bg-ink/[0.03] px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">Crawl depth (1–5)</label>
                    <input
                      type="number"
                      min={1}
                      max={5}
                      value={crawlerDepth}
                      onChange={(e) => setCrawlerDepth(Math.min(5, Math.max(1, Number(e.target.value) || 1)))}
                      className="w-full rounded-xl border-2 border-white bg-ink/[0.03] px-4 py-2.5 text-[13px] text-ink outline-none transition focus:border-deep-violet/40"
                    />
                  </div>
                </>
              )}
              {sourceType === "empty" && (
                <div className="rounded-xl bg-ink/[0.03] p-4 text-center">
                  <p className="text-[12px] text-ink/60">You can add sources later from the databank detail page.</p>
                </div>
              )}
              {sourceType === "database" && (
                <div className="rounded-xl bg-ink/[0.03] p-4 text-center">
                  <p className="text-[12px] text-ink/60">
                    After creation, open the <span className="font-bold">Databases</span> tab to connect
                    PostgreSQL or MySQL and ingest query results.
                  </p>
                </div>
              )}
            </div>
          )}

          {step === 4 && (
            <div className="space-y-2">
              <div className="rounded-xl bg-ink/[0.03] p-3">
                <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Name</p>
                <p className="text-[13px] text-ink">{name}</p>
              </div>
              {desc && (
                <div className="rounded-xl bg-ink/[0.03] p-3">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Description</p>
                  <p className="text-[12px] text-ink/70">{desc}</p>
                </div>
              )}
              <div className="rounded-xl bg-ink/[0.03] p-3">
                <p className="text-[10px] font-bold uppercase tracking-wide text-ink/40">Source</p>
                <p className="text-[12px] text-ink/70">
                  {sourceType === "files" && `${files.length} file(s) to upload`}
                  {sourceType === "crawler" && `Crawl ${crawlerUrl} (depth ${crawlerDepth})`}
                  {sourceType === "database" && "Live database — connect after creation"}
                  {sourceType === "empty" && "Start empty — add sources later"}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="mt-5 flex justify-between gap-2">
          <button
            onClick={step === 1 ? onClose : handleBack}
            className="rounded-xl border-2 border-ink/10 px-4 py-2 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.03]"
          >
            {step === 1 ? "Cancel" : "Back"}
          </button>
          {step < STEPS.length ? (
            <button
              onClick={handleNext}
              disabled={!canProceed()}
              className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90 disabled:opacity-40"
            >
              Continue
            </button>
          ) : (
            <button
              onClick={handleCreate}
              disabled={creating}
              className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90 disabled:opacity-40"
            >
              {creating ? "Creating..." : "Create Databank"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
