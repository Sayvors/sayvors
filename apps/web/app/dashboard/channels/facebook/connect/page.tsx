"use client";

import { Suspense } from "react";
import FacebookConnectFlow from "@/components/channels/connect/FacebookConnectFlow";

export default function FacebookConnectPage() {
  return (
    <Suspense>
      <FacebookConnectFlow />
    </Suspense>
  );
}
