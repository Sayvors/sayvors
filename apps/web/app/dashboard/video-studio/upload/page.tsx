"use client";

import { useState } from "react";
import Breadcrumbs from "@/components/video-studio/Breadcrumbs";
import VideoDropzone from "@/components/video-studio/VideoDropzone";
import VideoPreview from "@/components/video-studio/VideoPreview";
import PlatformCardsGrid from "@/components/video-studio/PlatformCardsGrid";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

export default function VideoStudioUploadPage() {
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string>("");

  const handleFileSelect = (file: File) => {
    setVideoFile(file);
    const url = URL.createObjectURL(file);
    setVideoUrl(url);
  };

  const handleRemove = () => {
    if (videoUrl) URL.revokeObjectURL(videoUrl);
    setVideoFile(null);
    setVideoUrl("");
  };

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="p-4 sm:p-6 space-y-5">
        <Breadcrumbs
          items={[
            { label: "Video Studio", href: "/dashboard/video-studio" },
            { label: "Upload Video" },
          ]}
        />

        <div>
          <h1 className="text-[20px] sm:text-[22px] font-bold text-ink">Upload Video</h1>
          <p className="mt-0.5 text-[12px] sm:text-[13px] text-ink/65">
            Upload your video and AI will optimize content for each platform.
          </p>
        </div>

        {!videoFile ? (
          <VideoDropzone onFileSelect={handleFileSelect} />
        ) : (
          <div className="space-y-5">
            <VideoPreview
              fileName={videoFile.name}
              fileUrl={videoUrl}
              fileSize={formatBytes(videoFile.size)}
              onRemove={handleRemove}
            />
            <PlatformCardsGrid videoFile={videoFile} videoUrl={videoUrl} />
          </div>
        )}
      </div>
    </div>
  );
}
