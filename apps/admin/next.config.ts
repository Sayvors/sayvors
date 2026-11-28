import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs/config";

const nextConfig: NextConfig = {
  experimental: {
    agentUpgrade: "security",
  },
  /* config options here */
};

export default withSentryConfig(nextConfig, {
  silent: !process.env.NEXT_PUBLIC_GLITCHTIP_DSN,
  widenClientFileUpload: true,
});
