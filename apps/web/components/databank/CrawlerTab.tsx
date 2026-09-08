"use client";

import { useState } from "react";

interface CrawlerTabProps {
  onCrawl: (url: string, mode: "single" | "full") => void;
}

export default function CrawlerTab({ onCrawl }: CrawlerTabProps) {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<"single" | "full">("single");

  const handleCrawl = () => {
    if (url.trim()) {
      onCrawl(url.trim(), mode);
    }
  };

  return (
    <div className="space-y-4">
      {/* Crawler Input */}
      <div className="rounded-xl border-2 border-white bg-white/60 p-5">
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
              <circle cx="12" cy="12" r="10" />
              <path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" />
            </svg>
          </div>
          <div>
            <p className="text-[13px] font-bold text-ink">Website Crawler</p>
            <p className="text-[11px] text-ink/45">Extract content from websites</p>
          </div>
        </div>

        <div className="space-y-3">
          <div>
            <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">URL</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com"
              className="w-full rounded-xl border-2 border-white bg-ink/[0.03] px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/40"
            />
          </div>

          <div>
            <label className="block text-[11px] font-semibold text-ink/50 mb-1.5">Crawl Mode</label>
            <div className="flex gap-2">
              <button
                onClick={() => setMode("single")}
                className={`flex-1 rounded-xl px-4 py-2.5 text-[12px] font-semibold transition ${
                  mode === "single"
                    ? "bg-deep-violet text-white shadow-md"
                    : "bg-ink/[0.04] text-ink/50 hover:bg-ink/[0.08]"
                }`}
              >
                <div className="flex items-center justify-center gap-2">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                    <rect x="3" y="3" width="18" height="18" rx="2" />
                  </svg>
                  Single Page
                </div>
              </button>
              <button
                onClick={() => setMode("full")}
                className={`flex-1 rounded-xl px-4 py-2.5 text-[12px] font-semibold transition ${
                  mode === "full"
                    ? "bg-deep-violet text-white shadow-md"
                    : "bg-ink/[0.04] text-ink/50 hover:bg-ink/[0.08]"
                }`}
              >
                <div className="flex items-center justify-center gap-2">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-4 w-4">
                    <path d="M3 12h4l3-9 4 18 3-9h4" />
                  </svg>
                  Full Site
                </div>
              </button>
            </div>
          </div>

          <button
            onClick={handleCrawl}
            disabled={!url.trim()}
            className="w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-[12px] font-bold text-white shadow-md transition hover:bg-emerald-600 disabled:opacity-40"
          >
            Add to Queue
          </button>

          <details className="rounded-xl border border-ink/[0.06] bg-ink/[0.02]">
            <summary className="cursor-pointer select-none px-3 py-2 text-[11px] font-bold uppercase tracking-wide text-ink/50 hover:text-ink/70">
              Single page vs. full site — which one?
            </summary>
            <div className="space-y-2 border-t border-ink/[0.05] px-3 py-3 text-[12px] text-ink/60">
              <p className="font-bold text-ink">Single page</p>
              <p>Indexes only the page you paste. Fast, predictable, and safe for one-off articles, help articles, or PDFs.</p>
              <p className="mt-1"><span className="text-emerald-600">Use when</span> you want exactly one URL and nothing else.</p>
              <p className="mt-0.5"><span className="text-amber-600">Watch out</span> linked pages are not followed, so a knowledge base spread across many URLs needs Full site.</p>
              <p className="mt-1 font-bold text-ink">Full site</p>
              <p>Follows internal links and crawls the whole domain up to a depth limit. Best for docs, blogs, and help centers.</p>
              <p className="mt-1"><span className="text-emerald-600">Use when</span> your knowledge lives across many pages of one site.</p>
              <p className="mt-0.5"><span className="text-amber-600">Watch out</span> large sites can take a while and may pull in navigation pages you do not want. Point it at a docs sub-path if the site is big.</p>
            </div>
          </details>
        </div>
      </div>

      {/* Crawl Stats */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl border-2 border-white bg-white/60 p-4 text-center">
          <p className="text-[20px] font-bold text-ink">0</p>
          <p className="text-[10px] text-ink/40">Pages Crawled</p>
        </div>
        <div className="rounded-xl border-2 border-white bg-white/60 p-4 text-center">
          <p className="text-[20px] font-bold text-ink">0</p>
          <p className="text-[10px] text-ink/40">Documents Created</p>
        </div>
      </div>
    </div>
  );
}
