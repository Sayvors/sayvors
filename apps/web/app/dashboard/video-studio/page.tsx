"use client";

import Link from "next/link";
import StatsRow from "@/components/video-studio/StatsRow";
import PlatformGrid from "@/components/video-studio/PlatformGrid";
import RecentVideos from "@/components/video-studio/RecentVideos";

export default function VideoStudioPage() {
  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="p-4 sm:p-6 space-y-5">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-[20px] sm:text-[22px] font-bold text-ink">Video Studio</h1>
            <p className="mt-0.5 text-[12px] sm:text-[13px] text-ink/65">
              Upload once, publish everywhere. AI-optimized content for each platform.
            </p>
          </div>
          <Link
            href="/dashboard/video-studio/upload"
            className="flex items-center gap-1.5 rounded-xl bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-[0.98]"
          >
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3.5 w-3.5">
              <path d="M8 3v10M3 8h10" strokeLinecap="round" />
            </svg>
            Upload Video
          </Link>
        </div>
        <StatsRow />
        <PlatformGrid />
        <RecentVideos />
      </div>
    </div>
  );
}
