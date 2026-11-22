"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchActiveUiJobs, type UiJob } from "@/lib/api-jobs";

const FOCUS = "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]";

function statusLabel(job: UiJob): string {
  if (job.status === "succeeded") return "Completed";
  if (job.status === "failed" || job.status === "dead") return job.progress_label || "Failed";
  if (job.status === "cancelled") return "Cancelled";
  if (job.status === "running") return job.progress_label || "Working…";
  if (job.status === "queued" || job.status === "accepted") return "Queued";
  if (job.status === "retrying") return "Retrying";
  if (job.status === "blocked") return "Waiting";
  return job.status;
}

function progressValue(job: UiJob): number {
  if (job.status === "succeeded") return 100;
  const p = Number(job.progress || 0);
  if (Number.isFinite(p)) return Math.max(0, Math.min(100, p));
  return 0;
}

function JobRow({ job }: { job: UiJob }) {
  const value = progressValue(job);
  return (
    <li className="rounded-[20px] border border-[var(--ui-line)] bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-semibold text-[var(--ui-ink)]">{job.ui_title || job.job_type}</p>
          <p className="mt-0.5 text-[11px] text-[var(--ui-ink-2)]">{statusLabel(job)}</p>
        </div>
        <span className="shrink-0 text-[11px] font-semibold text-[var(--ui-ink-2)]">{value}%</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#E9E3F3]" aria-hidden>
        <div className="h-full rounded-full bg-[#3D1D6E] transition-[width] duration-300" style={{ width: `${value}%` }} />
      </div>
      {job.last_error ? <p className="mt-2 text-[11px] text-red-600">{job.last_error}</p> : null}
    </li>
  );
}

export default function JobProgressProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [visible, setVisible] = useState(true);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const onVisibility = () => setVisible(document.visibilityState === "visible");
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const jobsQuery = useQuery({
    queryKey: ["jobs", "active-ui"],
    queryFn: ({ signal }) => fetchActiveUiJobs(signal),
    refetchInterval: visible ? 3000 : false,
    refetchIntervalInBackground: false,
  });

  const jobs = jobsQuery.data ?? [];
  const count = jobs.length;
  const avg = useMemo(() => {
    if (!count) return 0;
    return Math.round(jobs.reduce((sum, j) => sum + progressValue(j), 0) / count);
  }, [jobs, count]);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    panel?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
        buttonRef.current?.focus();
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      const focusable = panel.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
      if (focusable.length === 0) { e.preventDefault(); panel.focus(); return; }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      prev?.focus?.();
    };
  }, [open]);

  return (
    <>
      {children}
      <div aria-live="polite" className="sr-only">
        {count > 0 ? `${count} background operation${count === 1 ? "" : "s"} in progress` : "No background operations in progress"}
      </div>
      {count > 0 ? (
        <button
          ref={buttonRef}
          type="button"
          onClick={() => setOpen(true)}
          className={`fixed bottom-5 right-5 z-[60] flex h-14 w-14 items-center justify-center rounded-full border border-[var(--ui-line)] bg-white text-[#3D1D6E] shadow-[0_8px_24px_rgba(20,16,31,0.12)] ${FOCUS}`}
          aria-label={`Open background operations, ${count} in progress`}
        >
          <svg viewBox="0 0 36 36" className="h-10 w-10" aria-hidden>
            <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#E9E3F3" strokeWidth="3" />
            <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" fill="none" stroke="#3D1D6E" strokeWidth="3" strokeDasharray={`${avg}, 100`} strokeLinecap="round" />
            <text x="18" y="20.5" textAnchor="middle" fontSize="8" fill="#14101F" fontWeight="700">{count}</text>
          </svg>
        </button>
      ) : null}
      {open ? (
        <div className="fixed inset-0 z-[70]">
          <button type="button" aria-label="Close background operations" className="absolute inset-0 bg-black/20" onClick={() => setOpen(false)} />
          <aside
            ref={panelRef}
            tabIndex={-1}
            role="dialog"
            aria-modal="true"
            aria-label="Background operations"
            className="absolute bottom-0 right-0 top-0 w-full max-w-md border-l border-[var(--ui-line)] bg-[#F4F2F7] p-4 shadow-[0_8px_24px_rgba(20,16,31,0.16)] sm:p-5"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-[16px] font-bold text-[var(--ui-ink)]">Background operations</h2>
                <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">Work continues while you use the app.</p>
              </div>
              <button type="button" onClick={() => setOpen(false)} className={`rounded-[20px] border border-[var(--ui-line)] bg-white px-3 py-2 text-[12px] font-semibold text-[var(--ui-ink)] ${FOCUS}`}>Close</button>
            </div>
            <ul className="mt-4 space-y-3 overflow-y-auto pb-6" style={{ maxHeight: "calc(100vh - 8rem)" }}>
              {jobs.map((job) => <JobRow key={job.id} job={job} />)}
            </ul>
          </aside>
        </div>
      ) : null}
    </>
  );
}
