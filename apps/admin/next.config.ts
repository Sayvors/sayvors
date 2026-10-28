import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs/config";

const nextConfig: NextConfig = {
  /* config options here */
};

export default withSentryConfig(nextConfig, {
  silent: !process.env.NEXT_PUBLIC_GLITCHTIP_DSN,
  widenClientFileUpload: true,
});
