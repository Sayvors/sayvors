"use client";

import Image from "next/image";

interface PlatformIconProps {
  slug: string;
  icon: string;
  color: string;
  size?: "sm" | "md" | "lg";
}

export default function PlatformIcon({ slug, icon, color, size = "md" }: PlatformIconProps) {
  const sizes = { sm: "h-4 w-4", md: "h-5 w-5", lg: "h-7 w-7" };
  const containerSizes = { sm: "h-6 w-6", md: "h-10 w-10", lg: "h-14 w-14" };

  return (
    <div
      className={`flex ${containerSizes[size]} items-center justify-center rounded-xl text-white`}
      style={{ backgroundColor: color }}
    >
      <svg viewBox="0 0 24 24" fill="currentColor" className={sizes[size]}>
        <path d={icon} />
      </svg>
    </div>
  );
}
