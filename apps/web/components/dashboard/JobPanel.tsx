"use client";

import { useState, useEffect, useCallback } from "react";
import { listJobs } from "@/lib/api-rag";

type Job = {
  id: string;
  document_name: string;
  databank_name: string;
  status: "parsing" | "chunking" | "embedding" | "indexing" | "completed" | "failed";
  progress: number;
  error?: string;
};

const STAGE_LABELS: Record<string, string> = {
  parsing: "Parsing",
  chunking: "Chunking",
  embedding: "Embedding",
  indexing: "Indexing",
  completed: "Completed",
  failed: "Failed",
};

const STAGE_COLORS: Record<string, string> = {
  parsing: "bg-sky-400",
  chunking: "bg-amber-400",
  embedding: "bg-deep-violet",
  indexing: "bg-emerald-500",
  completed: "bg-emerald-500",
  failed: "bg-coral",
};

export default function JobPanel() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [expanded, setExpanded] = useState(false);
  const [completedAt, setCompletedAt] = useState<Record<string, number>>({});

  const fetchJobs = useCallback(async () => {
    try {
      const data = await listJobs();
      const active = Array.isArray(data) ? data : data.jobs || [];
      setJobs(active);
    } catch {
      /* empty */
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    const interval = setInterval(fetchJobs, 2000);
    return () => clearInterval(interval);
  }, [fetchJobs]);

  // Dismiss completed jobs after 10s
  useEffect(() => {
    const now = Date.now();
    const toDismiss: string[] = [];

    for (const job of jobs) {
      if (job.status === "completed" || job.status === "failed") {
        if (!completedAt[job.id]) {
          setCompletedAt((prev) => ({ ...prev, [job.id]: now }));
        } else if (now - completedAt[job.id] > 10_000) {
          toDismiss.push(job.id);
        }
      }
    }

    if (toDismiss.length > 0) {
      setJobs((prev) => prev.filter((j) => !toDismiss.includes(j.id)));
      setCompletedAt((prev) => {
        const next = { ...prev };
        for (const id of toDismiss) delete next[id];
        return next;
      });
    }
  }, [jobs, completedAt]);

  const activeJobs = jobs.filter((j) => j.status !== "completed" && j.status !== "failed");
  const finishedJobs = jobs.filter((j) => j.status === "completed" || j.status === "failed");
  const totalActive = activeJobs.length;

  if (jobs.length === 0) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50">
      {/* Collapsed pill */}
      {!expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="flex items-center gap-2 rounded-full bg-deep-violet px-4 py-2.5 text-[12px] font-semibold text-white shadow-lg transition hover:bg-deep-violet/90"
        >
          <div className="h-2 w-2 animate-pulse rounded-full bg-white" />
          <span>{totalActive} active job{totalActive !== 1 ? "s" : ""}</span>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
            <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}

      {/* Expanded panel */}
      {expanded && (
        <div className="w-80 rounded-xl border border-ink/[0.08] bg-white shadow-2xl dark:border-fog/[0.08] dark:bg-ink">
          <div className="flex items-center justify-between border-b border-ink/[0.06] px-4 py-3 dark:border-fog/[0.06]">
            <div className="flex items-center gap-2">
              <div className={`h-2 w-2 rounded-full ${totalActive > 0 ? "animate-pulse bg-deep-violet" : "bg-ink/20 dark:bg-fog/20"}`} />
              <p className="text-[13px] font-semibold text-ink dark:text-fog">Jobs</p>
              <span className="rounded-full bg-ink/[0.04] px-2 py-0.5 text-[10px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">
                {jobs.length}
              </span>
            </div>
            <button
              onClick={() => setExpanded(false)}
              className="rounded-md p-1 text-ink/30 transition hover:text-ink/60 dark:text-fog/30 dark:hover:text-fog/60"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
                <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>

          <div className="max-h-64 overflow-y-auto">
            {jobs.length === 0 ? (
              <div className="px-4 py-6 text-center">
                <p className="text-[12px] text-ink/30 dark:text-fog/30">No active jobs</p>
              </div>
            ) : (
              <div className="divide-y divide-ink/[0.06] dark:divide-fog/[0.06]">
                {jobs.map((job) => (
                  <div key={job.id} className="px-4 py-3">
                    <div className="flex items-start justify-between">
                      <div className="min-w-0 flex-1">
                        <p className="text-[12px] font-medium text-ink dark:text-fog truncate">{job.document_name}</p>
                        <p className="text-[10px] text-ink/35 dark:text-fog/35 truncate">{job.databank_name}</p>
                      </div>
                      {job.status === "failed" && (
                        <button className="shrink-0 rounded-md bg-coral/10 px-2 py-0.5 text-[10px] font-medium text-coral transition hover:bg-coral/20">
                          Retry
                        </button>
                      )}
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${STAGE_COLORS[job.status] || "bg-ink/20"}`} />
                      <span className="text-[10px] font-medium text-ink/50 dark:text-fog/50">
                        {STAGE_LABELS[job.status] || job.status}
                      </span>
                    </div>
                    {(job.status === "failed" && job.error) ? (
                      <p className="mt-1 text-[10px] text-coral">{job.error}</p>
                    ) : (
                      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{
                            width: `${job.progress ?? 0}%`,
                            backgroundColor: job.status === "completed" ? "#059669" : job.status === "failed" ? "#ff4f6e" : "#3d1d6e",
                          }}
                        />
                      </div>
                    )}
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
