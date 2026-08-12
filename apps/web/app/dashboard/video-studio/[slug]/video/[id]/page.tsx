"use client";

import { use } from "react";
import Breadcrumbs from "@/components/video-studio/Breadcrumbs";
import VideoHeader from "@/components/video-studio/VideoHeader";
import VideoMetrics from "@/components/video-studio/VideoMetrics";
import AudienceInsights from "@/components/video-studio/AudienceInsights";
import RetentionChart from "@/components/video-studio/RetentionChart";
import { getPlatform, getPlatformVideos } from "@/components/video-studio/platforms";

export default function VideoDetailPage({ params }: { params: Promise<{ slug: string; id: string }> }) {
  const { slug, id } = use(params);
  const platform = getPlatform(slug);
  const videos = getPlatformVideos(slug);
  const video = videos.find((v) => v.id === id);

  if (!platform || !video) {
    return (
      <div className="h-full overflow-y-auto bg-[#f3f0ff]">
        <div className="p-4 sm:p-6">
          <Breadcrumbs items={[{ label: "Video Studio", href: "/dashboard/video-studio" }, { label: "Not Found" }]} />
          <p className="mt-4 text-[14px] text-ink/50">Video not found.</p>
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
            { label: platform.name, href: `/dashboard/video-studio/${platform.slug}` },
            { label: video.title },
          ]}
        />

        <VideoHeader
          title={video.title}
          publishedAt={video.publishedAt}
          status={video.status}
          color={video.thumbnailColor}
        />

        <VideoMetrics video={video} />

        <div className="grid gap-4 lg:grid-cols-2">
          <RetentionChart />

          {/* Top comments */}
          <div className="rounded-2xl border-2 border-white bg-white/80 p-4">
            <h3 className="text-[12px] font-bold text-ink mb-3">Top Comments</h3>
            <div className="space-y-3">
              {[
                { user: "alex_dev", text: "This is exactly what I needed! Great tutorial.", likes: "234" },
                { user: "sarah.k", text: "Love the production quality! More like this please.", likes: "189" },
                { user: "mike_tech", text: "Very informative, shared with my team.", likes: "156" },
                { user: "lisa_creates", text: "The best content I've seen this week!", likes: "134" },
              ].map((comment, i) => (
                <div key={i} className="flex items-start gap-2.5">
                  <div className="h-6 w-6 shrink-0 rounded-full bg-deep-violet/10 flex items-center justify-center text-[9px] font-bold text-deep-violet">
                    {comment.user[0].toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-semibold text-ink">@{comment.user}</p>
                    <p className="text-[11px] text-ink/50 truncate">{comment.text}</p>
                  </div>
                  <span className="text-[9px] text-ink/30 shrink-0">❤️ {comment.likes}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <AudienceInsights />
      </div>
    </div>
  );
}
