export const PLATFORM_META: Record<string, { label: string; icon: string }> = {
  whatsapp: { label: "WhatsApp", icon: "/channels/whatsapp.png" },
  instagram: { label: "Instagram", icon: "/channels/instagram.png" },
  facebook: { label: "Facebook Messenger", icon: "/channels/facebook.png" },
  x: { label: "X", icon: "/channels/x.png" },
  telegram: { label: "Telegram", icon: "/channels/telegram.png" },
  linkedin: { label: "LinkedIn", icon: "/channels/linkedin.png" },
  tiktok: { label: "TikTok", icon: "/channels/tiktok.png" },
  snapchat: { label: "Snapchat", icon: "/channels/snapchat.png" },
};

export function platformMeta(platform: string | null): { label: string; icon: string | null } {
  if (!platform) return { label: "Unknown", icon: null };
  return PLATFORM_META[platform] ?? { label: platform, icon: null };
}
