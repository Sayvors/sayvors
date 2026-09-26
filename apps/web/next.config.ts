import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // The dev server rejects requests whose Origin is not on this list, and it
  // answers a blocked HMR websocket upgrade with 503. Facebook Login needs an
  // HTTPS origin, so local Meta testing goes through a tunnel (ngrok) whose
  // subdomain is randomly reassigned on every restart — hence the wildcard.
  // Dev-only: has no effect on `next build` / `next start`.
  allowedDevOrigins: ["*.ngrok-free.app", "*.ngrok.io", "*.trycloudflare.com"],
  images: {
    formats: ["image/avif", "image/webp"],
    minimumCacheTTL: 60 * 60 * 24 * 30,
  },
  experimental: {
    optimizePackageImports: ["lucide-react", "@heroicons/react"],
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-DNS-Prefetch-Control", value: "on" },
          // same-origin-allow-popups (not same-origin): Google Sign-In opens a
          // cross-origin popup that must keep window.opener to postMessage the
          // ID token back. same-origin severs the opener -> blank popup, no
          // callback, no server request.
          { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
          { key: "Cross-Origin-Embedder-Policy", value: "credentialless" },
        ],
      },
      {
        source: "/api/(.*)",
        headers: [
          { key: "Cache-Control", value: "no-store, no-cache, must-revalidate" },
          { key: "Pragma", value: "no-cache" },
        ],
      },
    ];
  },
};

export default nextConfig;
