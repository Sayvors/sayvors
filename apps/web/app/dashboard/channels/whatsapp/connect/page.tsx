"use client";

import { Suspense } from "react";
import WhatsAppConnectFlow from "@/components/channels/connect/WhatsAppConnectFlow";

export default function WhatsAppConnectPage() {
  return (
    <Suspense>
      <WhatsAppConnectFlow />
    </Suspense>
  );
}
