"use client";

import { useRef } from "react";

interface VideoDropzoneProps {
  onFileSelect: (file: File) => void;
}

export default function VideoDropzone({ onFileSelect }: VideoDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file && file.type.startsWith("video/")) {
      onFileSelect(file);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) onFileSelect(file);
  };

  return (
    <div
      onDrop={handleDrop}
      onDragOver={(e) => e.preventDefault()}
      onClick={() => inputRef.current?.click()}
      className="flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-deep-violet/20 bg-deep-violet/[0.03] px-6 py-12 text-center transition hover:border-deep-violet/40 hover:bg-deep-violet/[0.06] cursor-pointer"
    >
      <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-deep-violet/10">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-8 w-8 text-deep-violet">
          <polygon points="23 7 16 12 23 17 23 7" />
          <rect x="1" y="5" width="15" height="14" rx="2" />
        </svg>
      </div>
      <p className="mt-4 text-[14px] font-bold text-ink">Drop your video here</p>
      <p className="mt-1 text-[12px] text-ink/45">or click to browse</p>
      <p className="mt-2 text-[10px] text-ink/30">MP4, MOV, AVI up to 2GB</p>
      <input ref={inputRef} type="file" accept="video/*" onChange={handleChange} className="hidden" />
    </div>
  );
}
