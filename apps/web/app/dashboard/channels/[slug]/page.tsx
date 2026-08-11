"use client";

import { use } from "react";
import ChannelWorkspace from "@/components/dashboard/ChannelWorkspace";

export default function ChannelPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  return <ChannelWorkspace slug={slug} />;
}
