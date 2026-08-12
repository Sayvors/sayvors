"use client";

interface VideoPreviewProps {
  fileName: string;
  fileUrl: string;
  fileSize: string;
  onRemove: () => void;
}

export default function VideoPreview({ fileName, fileUrl, fileSize, onRemove }: VideoPreviewProps) {
  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 overflow-hidden">
      <div className="relative aspect-video bg-ink/[0.06]">
        {fileUrl ? (
          <video src={fileUrl} controls className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-12 w-12 text-ink/15">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
          </div>
        )}
      </div>
      <div className="flex items-center gap-3 px-4 py-3">
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold text-ink truncate">{fileName}</p>
          <p className="text-[11px] text-ink/40">{fileSize}</p>
        </div>
        <button
          onClick={onRemove}
          className="rounded-lg border-2 border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/50 transition hover:border-coral/30 hover:text-coral"
        >
          Remove
        </button>
      </div>
    </div>
  );
}
