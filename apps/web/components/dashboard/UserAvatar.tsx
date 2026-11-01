"use client";

import { useEffect, useState } from "react";

/**
 * Avatar with an initials fallback.
 *
 * Provider pictures (Google/Facebook) expire, uploads can outlive their
 * object, and a mixed-content URL is blocked outright. A broken <img> used to
 * paint the browser's broken-image icon on the purple square; this renders the
 * user's initials instead, without hiding a working picture.
 */
export default function UserAvatar({
  url,
  initials,
  className = "",
  textClassName = "",
}: {
  url?: string | null;
  initials: string;
  className?: string;
  textClassName?: string;
}) {
  const [failed, setFailed] = useState(false);

  // A new URL deserves a fresh attempt; the previous failure says nothing
  // about a replacement upload or a re-authenticated provider picture.
  useEffect(() => {
    setFailed(false);
  }, [url]);

  return (
    <span
      className={`flex shrink-0 items-center justify-center overflow-hidden rounded-[2px] bg-deep-violet font-semibold text-white ${className}`}
    >
      {url && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element -- runtime provider/upload URL
        <img
          src={url}
          alt=""
          referrerPolicy="no-referrer"
          className="h-full w-full object-cover"
          onError={() => setFailed(true)}
        />
      ) : (
        <span className={textClassName}>{initials}</span>
      )}
    </span>
  );
}
