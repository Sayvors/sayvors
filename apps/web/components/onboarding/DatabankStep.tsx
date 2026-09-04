"use client";

import { useState } from "react";
import { apiFetch, uploadFile } from "@/lib/api-rag";

interface DatabankStepProps {
  onComplete: () => void;
}

export default function DatabankStep({ onComplete }: DatabankStepProps) {
  const [databankName, setDatabankName] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setFiles((prev) => [...prev, ...Array.from(e.target.files!)]);
    }
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleCreate = async () => {
    if (!databankName.trim() || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const databank = await apiFetch("/api/v1/rag/databanks", {
        method: "POST",
        body: JSON.stringify({ name: databankName.trim() }),
      });
      // Upload each file (sequential — keeps request volume low and surfaces errors clearly)
      for (const file of files) {
        await uploadFile(databank.id, file);
      }
      onComplete();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to create databank");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <label className="block text-[13px] font-medium text-ink dark:text-fog">Databank name</label>
        <input
          type="text"
          value={databankName}
          onChange={(e) => setDatabankName(e.target.value)}
          placeholder="e.g. Product Knowledge Base"
          className="mt-1.5 w-full rounded-xl border border-ink/[0.08] bg-white px-4 py-2.5 text-[13px] text-ink placeholder:text-ink/30 focus:border-deep-violet focus:outline-none focus:ring-1 focus:ring-deep-violet dark:border-fog/[0.08] dark:bg-ink dark:text-fog dark:placeholder:text-fog/30"
        />
      </div>

      <div>
        <label className="block text-[13px] font-medium text-ink dark:text-fog">
          Upload documents <span className="text-ink/40 dark:text-fog/40 font-normal">(optional)</span>
        </label>
        <p className="text-[12px] text-ink/40 dark:text-fog/40 mt-0.5">PDF, TXT, MD, DOCX — these power your AI&apos;s answers</p>
        <label className="mt-2 flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-ink/[0.12] bg-ink/[0.02] p-8 transition hover:border-deep-violet/30 dark:border-fog/[0.12] dark:bg-fog/[0.02]">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="mb-2 h-8 w-8 text-ink/20 dark:text-fog/20">
            <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
          </svg>
          <span className="text-[12px] font-medium text-ink/40 dark:text-fog/40">Click to upload</span>
          <input type="file" className="hidden" multiple accept=".pdf,.txt,.md,.docx" onChange={handleFileChange} />
        </label>
      </div>

      {files.length > 0 && (
        <div className="space-y-2">
          {files.map((file, i) => (
            <div key={i} className="flex items-center gap-3 rounded-lg border border-ink/[0.06] bg-white px-3 py-2 dark:border-fog/[0.06] dark:bg-ink">
              <span className="text-[12px] text-ink dark:text-fog flex-1 truncate">{file.name}</span>
              <button onClick={() => removeFile(i)} className="text-ink/30 hover:text-coral dark:text-fog/30" disabled={submitting}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}

      {error && (
        <p className="text-[12px] text-red-600 dark:text-red-400">{error}</p>
      )}

      <button
        onClick={handleCreate}
        disabled={!databankName.trim() || submitting}
        className="rounded-xl bg-deep-violet px-6 py-2.5 text-[13px] font-semibold text-white transition hover:bg-deep-violet/90 disabled:opacity-30 disabled:cursor-not-allowed"
      >
        {submitting ? "Creating…" : files.length > 0 ? `Create & upload ${files.length} file${files.length === 1 ? "" : "s"}` : "Create Databank"}
      </button>
    </div>
  );
}
