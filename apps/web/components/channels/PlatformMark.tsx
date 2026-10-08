import Image from "next/image";

/**
 * Official provider marks live in /public/channels (same source the dashboard
 * sidebar uses). A workspace often has several channels with the same display
 * name on different networks, so the mark and the provider label are what
 * actually identify a channel - the name alone does not.
 */
const LOGOS: Record<string, string> = {
  whatsapp: "/channels/whatsapp.png",
  instagram: "/channels/instagram.png",
  facebook: "/channels/facebook.png",
  x: "/channels/x.png",
  telegram: "/channels/telegram.png",
  linkedin: "/channels/linkedin.png",
};

const LABELS: Record<string, string> = {
  whatsapp: "WhatsApp",
  instagram: "Instagram",
  facebook: "Messenger",
  x: "X",
  telegram: "Telegram",
  linkedin: "LinkedIn",
  google_reviews: "Google Business",
};

export function platformLabel(platform: string): string {
  return LABELS[platform] ?? platform;
}

export default function PlatformMark({
  platform,
  size = 16,
  className = "",
}: {
  platform: string;
  size?: number;
  className?: string;
}) {
  const src = LOGOS[platform];
  if (!src) {
    // No official mark (e.g. Google Business): a letter tile, not an emoji.
    const initial = (LABELS[platform] ?? platform).trim().charAt(0).toUpperCase();
    return (
      <span
        aria-hidden
        className={`inline-flex shrink-0 items-center justify-center rounded-[2px] border border-ink/10 bg-white/70 font-semibold text-ink/60 dark:border-fog/15 dark:bg-white/10 dark:text-fog/70 ${className}`}
        style={{ width: size, height: size, fontSize: Math.max(9, size - 6) }}
      >
        {initial}
      </span>
    );
  }
  return (
    <Image
      src={src}
      alt=""
      width={size}
      height={size}
      className={`shrink-0 object-contain ${className}`}
      style={{ width: size, height: size }}
    />
  );
}