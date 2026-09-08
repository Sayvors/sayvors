"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listDatabanks, deleteDatabank } from "@/lib/api-rag";

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

export default function DatabankPage() {
  const [databanks, setDatabanks] = useState<Databank[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

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

  async function handleDelete(id: string) {
    try {
      await deleteDatabank(id);
      setDatabanks((prev) => prev.filter((db) => db.id !== id));
      if (selectedId === id) {
        setSelectedId(null);
      }
    } catch {
      // Keep UI resilient even if delete fails.
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="space-y-5 p-4 sm:p-6">
        <div className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
          <div>
            <h1 className="text-[20px] font-bold text-ink sm:text-[22px]">Databanks</h1>
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

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {loading
            ? Array.from({ length: 4 }).map((_, index) => (
                <div key={index} className="animate-pulse rounded-2xl border-2 border-white bg-white/80 p-4">
                  <div className="h-4 w-24 rounded-lg bg-ink/[0.06]" />
                  <div className="mt-3 h-3 w-16 rounded-lg bg-ink/[0.04]" />
                </div>
              ))
            : databanks.map((db) => {
                const isSelected = selectedId === db.id;
                return (
                  <button
                    key={db.id}
                    type="button"
                    onClick={() => setSelectedId(isSelected ? null : db.id)}
                    className={[
                      "rounded-2xl border-2 p-4 text-left transition",
                      isSelected ? "border-deep-violet bg-white shadow-md" : "border-white bg-white/80 hover:border-deep-violet/20",
                    ].join(" ")}
                  >
                    <div className="mb-3 flex items-center justify-between gap-2">
                      <div
                        className="flex h-10 w-10 items-center justify-center rounded-xl text-white shadow-md"
                        style={{ backgroundColor: db.accent_color || "#3d1d6e" }}
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
                          <ellipse cx="12" cy="5" rx="9" ry="3" />
                          <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                          <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                        </svg>
                      </div>

                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void handleDelete(db.id);
                        }}
                        className="rounded-lg border border-ink/10 px-2 py-1 text-[10px] font-semibold text-ink/50 transition hover:text-coral"
                      >
                        Delete
                      </button>
                    </div>

                    <div className="text-[14px] font-bold text-ink">{db.name}</div>
                    <div className="mt-1 text-[11px] text-ink/50">{db.description || "No description"}</div>

                    <div className="mt-4 flex items-center justify-between text-[11px] text-ink/55">
                      <span>{db.doc_count ?? 0} docs</span>
                      <span>{formatBytes(db.total_size ?? 0)}</span>
                    </div>
                  </button>
                );
              })}
        </div>

        {!loading && databanks.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-ink/10 bg-white/60 px-6 py-16 text-center">
            <div className="flex h-20 w-20 items-center justify-center rounded-3xl bg-deep-violet/10">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-10 w-10 text-deep-violet">
                <ellipse cx="12" cy="5" rx="9" ry="3" />
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
              </svg>
            </div>
            <h2 className="mt-4 text-[18px] font-bold text-ink">Create your first databank</h2>
            <p className="mt-2 max-w-sm text-[13px] text-ink/50">
              Start by uploading files, crawling a site, or creating a blank knowledge base for your AI agents.
            </p>
            <Link
              href="/dashboard/databank/new"
              className="mt-4 rounded-xl bg-deep-violet px-6 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-deep-violet/90"
            >
              + Create Databank
            </Link>
          </div>
        )}

        {selected && (
          <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">Selected databank</p>
                <h2 className="mt-1 text-[20px] font-bold text-ink">{selected.name}</h2>
              </div>
              <Link
                href="/dashboard/databank/new"
                className="rounded-xl border border-ink/10 bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02]"
              >
                Add source
              </Link>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <div className="rounded-2xl bg-ink/[0.02] p-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">Documents</div>
                <div className="mt-2 text-[22px] font-bold text-ink">{selected.doc_count ?? 0}</div>
              </div>
              <div className="rounded-2xl bg-ink/[0.02] p-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">Size</div>
                <div className="mt-2 text-[22px] font-bold text-ink">{formatBytes(selected.total_size ?? 0)}</div>
              </div>
              <div className="rounded-2xl bg-ink/[0.02] p-3">
                <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/45">Status</div>
                <div className="mt-2 text-[22px] font-bold text-emerald-600">Ready</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
