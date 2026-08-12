"use client";

import { use } from "react";
import Breadcrumbs from "@/components/video-studio/Breadcrumbs";
import PlatformIcon from "@/components/video-studio/PlatformIcon";
import PlatformStats from "@/components/video-studio/PlatformStats";
import VideoListItem from "@/components/video-studio/VideoListItem";
import { getPlatform, getPlatformAnalytics, getPlatformVideos } from "@/components/video-studio/platforms";

export default function PlatformDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const platform = getPlatform(slug);
  const analytics = getPlatformAnalytics(slug);
  const videos = getPlatformVideos(slug);

  if (!platform || !analytics) {
    return (
      <div className="h-full overflow-y-auto bg-[#f3f0ff]">
        <div className="p-4 sm:p-6">
          <Breadcrumbs items={[{ label: "Video Studio", href: "/dashboard/video-studio" }, { label: "Not Found" }]} />
          <p className="mt-4 text-[14px] text-ink/50">Platform not found.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="p-4 sm:p-6 space-y-5">
        <Breadcrumbs
          items={[
            { label: "Video Studio", href: "/dashboard/video-studio" },
            { label: platform.name },
          ]}
        />

        {/* Header */}
        <div className="flex items-center gap-4">
          <PlatformIcon slug={platform.slug} icon={platform.icon} color={platform.color} size="lg" />
          <div>
            <h1 className="text-[20px] sm:text-[22px] font-bold text-ink">{platform.name}</h1>
            <p className="mt-0.5 text-[12px] text-ink/50">
              {videos.length} videos · {platform.maxDuration} max · {platform.aspectRatio}
            </p>
          </div>
        </div>

        {/* Stats */}
        <PlatformStats analytics={analytics} />

        {/* Videos list */}
        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-[14px] font-bold text-ink">Videos</h2>
            <span className="text-[11px] text-ink/40">{videos.length} total</span>
          </div>
          <div className="rounded-2xl border-2 border-white bg-white/80 overflow-hidden">
            {videos.length === 0 ? (
              <div className="px-4 py-8 text-center">
                <p className="text-[12px] text-ink/35">No videos yet</p>
              </div>
            ) : (
              videos.map((video) => (
                <VideoListItem
                  key={video.id}
                  video={video}
                  platformSlug={platform.slug}
                  platformColor={platform.color}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
