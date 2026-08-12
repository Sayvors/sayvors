"use client";

import { useState } from "react";
import PlatformIcon from "./PlatformIcon";
import AIButton from "./AIButton";
import type { Platform } from "./platforms";

interface PlatformCardProps {
  platform: Platform;
  videoFile: File | null;
  videoUrl: string;
  selected: boolean;
  onToggleSelect: () => void;
  onUploadComplete: (slug: string) => void;
}

export default function PlatformCard({ platform, videoFile, videoUrl, selected, onToggleSelect, onUploadComplete }: PlatformCardProps) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [hashtags, setHashtags] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [uploaded, setUploaded] = useState(false);
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduleTime, setScheduleTime] = useState("");
  const [showSchedule, setShowSchedule] = useState(false);

  const handleGenerate = () => {
    setGenerating(true);
    setTimeout(() => {
      const name = videoFile?.name?.replace(/\.[^.]+$/, "") || "video";
      setTitle(`${name} - ${platform.name} Edition`);
      setDescription(`Check out this amazing content optimized for ${platform.name}! 🎬`);
      setHashtags(`#${name.replace(/\s+/g, "")} #content #viral #${platform.name}`);
      setGenerating(false);
      setGenerated(true);
    }, 1500);
  };

  const handleUpload = () => {
    setUploaded(true);
    onUploadComplete(platform.slug);
    setTimeout(() => setUploaded(false), 3000);
  };

  return (
    <div className={`rounded-2xl border-2 overflow-hidden transition ${selected ? "border-deep-violet/40 bg-deep-violet/[0.02] shadow-md" : "border-white bg-white/80 hover:shadow-md"}`}>
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-ink/[0.04]">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggleSelect}
          className="h-4 w-4 shrink-0 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/30 cursor-pointer"
        />
        <PlatformIcon slug={platform.slug} icon={platform.icon} color={platform.color} size="sm" />
        <div className="flex-1">
          <h3 className="text-[13px] font-bold text-ink">{platform.name}</h3>
          <p className="text-[10px] text-ink/40">
            {platform.maxDuration} · {platform.aspectRatio}
          </p>
        </div>
        <AIButton onClick={handleGenerate} loading={generating} />
      </div>

      {/* Content */}
      <div className="p-4 space-y-3">
        {/* Video preview */}
        {videoUrl && (
          <div className="relative aspect-video rounded-xl overflow-hidden bg-ink/[0.06]">
            <video src={videoUrl} muted className="h-full w-full object-cover" />
            <div className="absolute inset-0 flex items-center justify-center bg-black/20 opacity-0 hover:opacity-100 transition">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/90">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-5 w-5 text-ink">
                  <polygon points="5 3 19 12 5 21 5 3" fill="currentColor" />
                </svg>
              </div>
            </div>
          </div>
        )}

        {/* Title */}
        <div>
          <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Title</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={`Add title for ${platform.name}...`}
            className="mt-1 w-full rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink placeholder:text-ink/25 transition focus:border-deep-violet/30 focus:outline-none"
          />
        </div>

        {/* Description */}
        <div>
          <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={`Add description for ${platform.name}...`}
            rows={3}
            className="mt-1 w-full rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink placeholder:text-ink/25 transition focus:border-deep-violet/30 focus:outline-none resize-none"
          />
        </div>

        {/* Hashtags */}
        <div>
          <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Hashtags</label>
          <input
            type="text"
            value={hashtags}
            onChange={(e) => setHashtags(e.target.value)}
            placeholder="Add hashtags..."
            className="mt-1 w-full rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink placeholder:text-ink/25 transition focus:border-deep-violet/30 focus:outline-none"
          />
        </div>

        {/* Schedule toggle */}
        <button
          onClick={() => setShowSchedule(!showSchedule)}
          className="flex items-center gap-1.5 text-[11px] font-semibold text-deep-violet transition hover:text-deep-violet/80"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
            <rect x="3" y="4" width="18" height="18" rx="2" />
            <path d="M16 2v4M8 2v4M3 10h18" />
          </svg>
          {showSchedule ? "Hide Schedule" : "Schedule Post"}
        </button>

        {/* Schedule fields */}
        {showSchedule && (
          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Date</label>
              <input
                type="date"
                value={scheduleDate}
                onChange={(e) => setScheduleDate(e.target.value)}
                className="mt-1 w-full rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink transition focus:border-deep-violet/30 focus:outline-none"
              />
            </div>
            <div className="flex-1">
              <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Time</label>
              <input
                type="time"
                value={scheduleTime}
                onChange={(e) => setScheduleTime(e.target.value)}
                className="mt-1 w-full rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink transition focus:border-deep-violet/30 focus:outline-none"
              />
            </div>
          </div>
        )}

        {/* Upload / Schedule button */}
        <button
          onClick={handleUpload}
          disabled={uploaded}
          className={`w-full rounded-xl px-4 py-2.5 text-[12px] font-bold transition active:scale-[0.98] ${
            uploaded
              ? "bg-emerald-500 text-white"
              : showSchedule && scheduleDate && scheduleTime
              ? "bg-amber-500 text-white shadow-md shadow-amber-500/25 hover:bg-amber-600"
              : generated
              ? "bg-deep-violet text-white shadow-md shadow-deep-violet/25 hover:bg-deep-violet/90"
              : "bg-ink/[0.06] text-ink/30 cursor-not-allowed"
          }`}
        >
          {uploaded ? (
            <span className="flex items-center justify-center gap-1.5">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" className="h-3.5 w-3.5">
                <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Uploaded to {platform.name}
            </span>
          ) : showSchedule && scheduleDate && scheduleTime ? (
            <span className="flex items-center justify-center gap-1.5">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                <rect x="3" y="4" width="18" height="18" rx="2" />
                <path d="M16 2v4M8 2v4M3 10h18" />
              </svg>
              Schedule for {scheduleDate} {scheduleTime}
            </span>
          ) : (
            `Upload to ${platform.name}`
          )}
        </button>
      </div>
    </div>
  );
}
