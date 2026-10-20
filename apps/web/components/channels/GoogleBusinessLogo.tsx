"use client";

/*
 * Google Business Profile badge — inline SVG, no external image asset needed.
 * Google's four brand colours (solid fills per AGENTS.md): blue #4285F4,
 * red #EA4335, yellow #FBBC05, green #34A853, around a white "G".
 */
export default function GoogleBusinessLogo({
  className = "",
  size = 16,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={`shrink-0 ${className}`}
      aria-hidden
    >
      <defs>
        <clipPath id="g-clip">
          <circle cx="12" cy="12" r="10" />
        </clipPath>
      </defs>

      {/* Coloured circle segments behind the G */}
      <circle cx="12" cy="12" r="10" fill="#4285F4" clipPath="url(#g-clip)" />
      <path
        d="M22 12c0-5.52-4.48-10-10-10S2 6.48 2 12s4.48 10 10 10 10-4.48 10-10z"
        fill="#EA4335"
        clipPath="url(#g-clip)"
      />
      <path
        d="M12 22c-5.52 0-10-4.48-10-10S6.48 2 12 2s10 4.48 10 10-4.48 10-10 10z"
        fill="#FBBC05"
        clipPath="url(#g-clip)"
      />
      <path
        d="M2 12c0 5.52 4.48 10 10 10S22 17.52 22 12s-4.48-10-10-10S2 6.48 2 12z"
        fill="#34A853"
        clipPath="url(#g-clip)"
      />

      {/* White "G" cutout */}
      <path
        d="M12 4c-4.42 0-8 3.58-8 8s3.58 8 8 8 8-3.58 8-8-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6s2.69-6 6-6 6 2.69 6 6-2.69 6-6 6zm0-12c-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4-1.79-4-4-4zm0 6c-1.1 0-2-.9-2-2s.9-2 2-2 2 .9 2 2-.9 2-2 2z"
        fill="#FFFFFF"
        clipPath="url(#g-clip)"
      />
    </svg>
  );
}
