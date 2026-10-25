"use client";

import { Suspense } from "react";
import InstagramConnectFlow from "@/components/channels/connect/InstagramConnectFlow";

export default function InstagramConnectPage() {
  return (
    <Suspense>
      <InstagramConnectFlow />
    </Suspense>
  );
}
