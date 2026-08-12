export interface Platform {
  name: string;
  slug: string;
  color: string;
  icon: string;
  maxDuration: string;
  aspectRatio: string;
  maxFileSize: string;
}

export interface PlatformAnalytics {
  followers: string;
  totalViews: string;
  avgEngagement: string;
  avgWatchTime: string;
  topRegion: string;
  growth: string;
}

export interface Video {
  id: string;
  title: string;
  views: string;
  likes: string;
  comments: string;
  shares: string;
  watchTime: string;
  retention: string;
  publishedAt: string;
  status: "published" | "scheduled" | "draft";
  thumbnailColor: string;
}

export const platformAnalytics: Record<string, PlatformAnalytics> = {
  youtube: { followers: "125K", totalViews: "2.4M", avgEngagement: "8.3%", avgWatchTime: "4:32", topRegion: "United States", growth: "+12.5%" },
  instagram: { followers: "89K", totalViews: "1.1M", avgEngagement: "12.5%", avgWatchTime: "0:15", topRegion: "United Kingdom", growth: "+8.2%" },
  tiktok: { followers: "340K", totalViews: "8.7M", avgEngagement: "22.1%", avgWatchTime: "0:28", topRegion: "India", growth: "+45.3%" },
  facebook: { followers: "42K", totalViews: "580K", avgEngagement: "6.7%", avgWatchTime: "0:45", topRegion: "Canada", growth: "+3.1%" },
  linkedin: { followers: "18K", totalViews: "210K", avgEngagement: "5.2%", avgWatchTime: "1:12", topRegion: "Germany", growth: "+15.8%" },
  x: { followers: "67K", totalViews: "1.8M", avgEngagement: "9.8%", avgWatchTime: "0:22", topRegion: "Japan", growth: "+6.4%" },
};

export const platformVideos: Record<string, Video[]> = {
  youtube: [
    { id: "yt-1", title: "Product Launch Full Demo", views: "45.2K", likes: "3.2K", comments: "412", shares: "189", watchTime: "8:24", retention: "72%", publishedAt: "2 hours ago", status: "published", thumbnailColor: "#FF0000" },
    { id: "yt-2", title: "Tutorial - Getting Started Guide", views: "23.1K", likes: "1.8K", comments: "203", shares: "95", watchTime: "12:05", retention: "65%", publishedAt: "2 days ago", status: "published", thumbnailColor: "#FF6600" },
    { id: "yt-3", title: "Behind the Scenes - Office Tour", views: "18.7K", likes: "2.1K", comments: "156", shares: "78", watchTime: "6:48", retention: "58%", publishedAt: "5 days ago", status: "published", thumbnailColor: "#CC0000" },
    { id: "yt-4", title: "Customer Success Story", views: "12.3K", likes: "1.4K", comments: "89", shares: "45", watchTime: "5:12", retention: "70%", publishedAt: "1 week ago", status: "published", thumbnailColor: "#990000" },
  ],
  instagram: [
    { id: "ig-1", title: "Reel - Quick Tips", views: "32.1K", likes: "5.4K", comments: "312", shares: "445", watchTime: "0:15", retention: "92%", publishedAt: "1 hour ago", status: "published", thumbnailColor: "#E4405F" },
    { id: "ig-2", title: "Carousel - Feature Highlights", views: "18.9K", likes: "3.2K", comments: "178", shares: "234", watchTime: "0:12", retention: "88%", publishedAt: "3 days ago", status: "published", thumbnailColor: "#C13584" },
    { id: "ig-3", title: "Story - Team Poll", views: "8.4K", likes: "1.1K", comments: "45", shares: "12", watchTime: "0:08", retention: "95%", publishedAt: "4 days ago", status: "published", thumbnailColor: "#FD1D1D" },
  ],
  tiktok: [
    { id: "tt-1", title: "Trending Dance Challenge", views: "128.7K", likes: "42.1K", comments: "3.2K", shares: "8.9K", watchTime: "0:28", retention: "94%", publishedAt: "3 hours ago", status: "published", thumbnailColor: "#010101" },
    { id: "tt-2", title: "Day in the Life", views: "89.3K", likes: "28.4K", comments: "2.1K", shares: "5.6K", watchTime: "0:22", retention: "87%", publishedAt: "1 day ago", status: "published", thumbnailColor: "#00F2EA" },
    { id: "tt-3", title: "Product Unboxing", views: "56.2K", likes: "18.7K", comments: "1.4K", shares: "3.2K", watchTime: "0:18", retention: "91%", publishedAt: "3 days ago", status: "published", thumbnailColor: "#FF0050" },
    { id: "tt-4", title: "Quick Tutorial Hack", views: "201K", likes: "65.3K", comments: "4.8K", shares: "12.1K", watchTime: "0:15", retention: "96%", publishedAt: "1 week ago", status: "published", thumbnailColor: "#69C9D0" },
  ],
  facebook: [
    { id: "fb-1", title: "Company Announcement", views: "18.9K", likes: "2.1K", comments: "345", shares: "123", watchTime: "0:45", retention: "62%", publishedAt: "5 hours ago", status: "published", thumbnailColor: "#1877F2" },
    { id: "fb-2", title: "Live Q&A Recap", views: "12.3K", likes: "1.5K", comments: "234", shares: "67", watchTime: "1:20", retention: "55%", publishedAt: "2 days ago", status: "published", thumbnailColor: "#4267B2" },
  ],
  linkedin: [
    { id: "li-1", title: "Industry Insights Webinar", views: "8.4K", likes: "890", comments: "156", shares: "89", watchTime: "1:12", retention: "68%", publishedAt: "1 day ago", status: "published", thumbnailColor: "#0A66C2" },
    { id: "li-2", title: "Team Achievement Post", views: "5.2K", likes: "670", comments: "89", shares: "34", watchTime: "0:35", retention: "74%", publishedAt: "4 days ago", status: "published", thumbnailColor: "#0077B5" },
  ],
  x: [
    { id: "x-1", title: "Product Thread", views: "56.3K", likes: "4.2K", comments: "890", shares: "1.2K", watchTime: "0:22", retention: "78%", publishedAt: "4 hours ago", status: "published", thumbnailColor: "#000000" },
    { id: "x-2", title: "Quick Update", views: "34.1K", likes: "2.8K", comments: "456", shares: "678", watchTime: "0:18", retention: "82%", publishedAt: "1 day ago", status: "published", thumbnailColor: "#1DA1F2" },
    { id: "x-3", title: "Industry Commentary", views: "23.5K", likes: "1.9K", comments: "234", shares: "445", watchTime: "0:15", retention: "85%", publishedAt: "3 days ago", status: "published", thumbnailColor: "#14171A" },
  ],
};

export function getPlatform(slug: string): Platform | undefined {
  return platforms.find((p) => p.slug === slug);
}

export function getPlatformAnalytics(slug: string): PlatformAnalytics | undefined {
  return platformAnalytics[slug];
}

export function getPlatformVideos(slug: string): Video[] {
  return platformVideos[slug] || [];
}

export const platforms: Platform[] = [
  { name: "YouTube", slug: "youtube", color: "#FF0000", icon: "M23.5 6.5a3 3 0 00-2.1-2.1C19.5 4 12 4 12 4s-7.5 0-9.4.4a3 3 0 00-2.1 2.1C0 8.4 0 12 0 12s0 3.6.5 5.5a3 3 0 002.1 2.1c1.9.4 9.4.4 9.4.4s7.5 0 9.4-.4a3 3 0 002.1-2.1c.5-1.9.5-5.5.5-5.5s0-3.6-.5-5.5zM9.5 15.5V8.5l6.3 3.5-6.3 3.5z", maxDuration: "12 hours", aspectRatio: "16:9", maxFileSize: "256 GB" },
  { name: "Instagram", slug: "instagram", color: "#E4405F", icon: "M12 2.2c3.2 0 3.6 0 4.8.1 1.2.1 1.8.2 2.2.4.6.2 1 .5 1.4.9.4.4.7.8.9 1.4.2.4.3 1.1.4 2.2.1 1.3.1 1.6.1 4.8s0 3.6-.1 4.8c-.1 1.2-.2 1.8-.4 2.2-.2.6-.5 1-.9 1.4-.4.4-.8.7-1.4.9-.4.2-1.1.3-2.2.4-1.3.1-1.6.1-4.8.1s-3.6 0-4.8-.1c-1.2-.1-1.8-.2-2.2-.4-.6-.2-1-.5-1.4-.9-.4-.4-.7-.8-.9-1.4-.2-.4-.3-1.1-.4-2.2-.1-1.3-.1-1.6-.1-4.8s0-3.6.1-4.8c.1-1.2.2-1.8.4-2.2.2-.6.5-1 .9-1.4.4-.4.8-.7 1.4-.9.4-.2 1.1-.3 2.2-.4 1.3-.1 1.6-.1 4.8-.1M12 0C8.7 0 8.3 0 7.1.1 5.8.1 4.9.3 4.1.6c-.8.3-1.5.7-2.2 1.4C1.2 2.6.8 3.3.5 4.1.2 4.9 0 5.8 0 7.1 0 8.3 0 8.7 0 12s0 3.7.1 4.9c0 1.3.2 2.2.5 3 .3.8.7 1.5 1.4 2.2.7.7 1.4 1.1 2.2 1.4.8.3 1.7.5 3 .5 1.2.1 1.6.1 4.9.1s3.7 0 4.9-.1c1.3 0 2.2-.2 3-.5.8-.3 1.5-.7 2.2-1.4.7-.7 1.1-1.4 1.4-2.2.3-.8.5-1.7.5-3 .1-1.2.1-1.6.1-4.9s0-3.7-.1-4.9c0-1.3-.2-2.2-.5-3-.3-.8-.7-1.5-1.4-2.2C20.7 1.2 20 .8 19.2.5c-.8-.3-1.7-.5-3-.5C15.1 0 14.7 0 12 0zm0 5.8a6.2 6.2 0 100 12.4 6.2 6.2 0 000-12.4zM12 16a4 4 0 110-8 4 4 0 010 8zm6.4-10.8a1.4 1.4 0 11-2.8 0 1.4 1.4 0 012.8 0z", maxDuration: "60 min", aspectRatio: "9:16 / 1:1 / 16:9", maxFileSize: "650 MB" },
  { name: "TikTok", slug: "tiktok", color: "#010101", icon: "M19.6 3h-3.2a4.3 4.3 0 00-4.2 4.3v3.1H9V11h3.2v9.3a3.3 3.3 0 003.3 3.3 3.3 3.3 0 003.3-3.3 3.3 3.3 0 00-3.3-3.3h-1.1v-3h1.1a4.3 4.3 0 004.2-4.3V7.6a3.3 3.3 0 00-3.3-3.3zm-3.2 4.3a1.1 1.1 0 011.1-1.1h1.1V3.1h-3.2a3.3 3.3 0 00-3.2 3.3v3.1h3.2V7.6z", maxDuration: "10 min", aspectRatio: "9:16", maxFileSize: "287.6 MB" },
  { name: "Facebook", slug: "facebook", color: "#1877F2", icon: "M24 12c0-6.6-5.4-12-12-12S0 5.4 0 12c0 6 4.4 11 10.1 11.9v-8.4H7.1V12h3V9.4c0-3 1.8-4.7 4.5-4.7 1.3 0 2.7.2 2.7.2v3h-1.5c-1.5 0-2 .9-2 1.9V12h3.4l-.5 3.5h-2.9v8.4C19.6 23 24 18 24 12z", maxDuration: "240 min", aspectRatio: "16:9 / 9:16 / 1:1", maxFileSize: "10 GB" },
  { name: "LinkedIn", slug: "linkedin", color: "#0A66C2", icon: "M20.5 2h-17A1.5 1.5 0 002 3.5v17A1.5 1.5 0 003.5 22h17a1.5 1.5 0 001.5-1.5v-17A1.5 1.5 0 0020.5 2zM8 19H5v-9h3zM6.5 8.25A1.75 1.75 0 118.3 6.5a1.78 1.78 0 01-1.8 1.75zM19 19h-3v-4.74c0-1.42-.6-1.93-1.38-1.93A1.74 1.74 0 0013 14.19a.66.66 0 000 .14V19h-3v-9h2.9v1.3a3.11 3.11 0 012.7-1.4c1.55 0 3.36.86 3.36 3.66z", maxDuration: "10 min", aspectRatio: "16:9 / 1:1 / 9:16", maxFileSize: "5 GB" },
  { name: "X / Twitter", slug: "x", color: "#000000", icon: "M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z", maxDuration: "2 min 20s", aspectRatio: "16:9 / 1:1", maxFileSize: "512 MB" },
];
