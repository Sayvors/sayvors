"use client";

import { useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import PlatformCard from "./PlatformCard";
import { platforms } from "./platforms";

interface PlatformCardsGridProps {
  videoFile: File | null;
  videoUrl: string;
}

export default function PlatformCardsGrid({ videoFile, videoUrl }: PlatformCardsGridProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set(platforms.map((p) => p.slug)));
  const [uploadedSlugs, setUploadedSlugs] = useState<Set<string>>(new Set());
  const [uploadingAll, setUploadingAll] = useState(false);

  const toggleSelect = (slug: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === platforms.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(platforms.map((p) => p.slug)));
    }
  };

  const handleUploadComplete = (slug: string) => {
    setUploadedSlugs((prev) => new Set(prev).add(slug));
  };

  const handleUploadAll = () => {
    setUploadingAll(true);
    const allSlugs = platforms.map((p) => p.slug);
    let delay = 0;
    for (const slug of allSlugs) {
      setTimeout(() => {
        setUploadedSlugs((prev) => new Set(prev).add(slug));
        if (slug === allSlugs[allSlugs.length - 1]) setUploadingAll(false);
      }, delay);
      delay += 300;
    }
  };

  const handleUploadSelected = () => {
    const slugsToUpload = Array.from(selected).filter((s) => !uploadedSlugs.has(s));
    let delay = 0;
    for (const slug of slugsToUpload) {
      setTimeout(() => {
        setUploadedSlugs((prev) => new Set(prev).add(slug));
      }, delay);
      delay += 300;
    }
  };

  const allUploaded = platforms.every((p) => uploadedSlugs.has(p.slug));
  const selectedAllUploaded = Array.from(selected).every((s) => uploadedSlugs.has(s));

  return (
    <div>
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-3">
          <h2 className="text-[14px] font-bold text-ink">Platform Content</h2>
          <label className="flex items-center gap-1.5 text-[11px] text-ink/50 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={selected.size === platforms.length}
              onChange={toggleAll}
              className="h-3.5 w-3.5 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/30"
            />
            Select All
          </label>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-ink/40">
            {selected.size} selected · {uploadedSlugs.size} uploaded
          </span>
          <button
            onClick={handleUploadSelected}
            disabled={selected.size === 0 || selectedAllUploaded}
            className="flex items-center gap-1.5 rounded-lg border-2 border-deep-violet/20 bg-deep-violet/5 px-3 py-1.5 text-[11px] font-bold text-deep-violet transition hover:bg-deep-violet/10 active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
              <path d="M12 5v14M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Upload Selected
          </button>
          <button
            onClick={handleUploadAll}
            disabled={allUploaded || uploadingAll}
            className="flex items-center gap-1.5 rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {uploadingAll ? (
              <>
                <LogoLoader size={14} />
                Uploading...
              </>
            ) : allUploaded ? (
              <>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className="h-3 w-3">
                  <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                All Uploaded
              </>
            ) : (
              <>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                  <path d="M12 5v14M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Upload to All
              </>
            )}
          </button>
        </div>
      </div>

      {/* Grid */}
      <div className="grid gap-4 lg:grid-cols-2">
        {platforms.map((platform) => (
          <PlatformCard
            key={platform.slug}
            platform={platform}
            videoFile={videoFile}
            videoUrl={videoUrl}
            selected={selected.has(platform.slug)}
            onToggleSelect={() => toggleSelect(platform.slug)}
            onUploadComplete={handleUploadComplete}
          />
        ))}
      </div>
    </div>
  );
}
