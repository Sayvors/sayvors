"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import LogoLoader from "@/components/LogoLoader";

/** Legacy detail links now open the bounded, evidence-rich Compare page. */
export default function BenchmarkDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  useEffect(() => {
    if (!id) return;
    router.replace(
      `/dashboard/benchmark/compare?main=${encodeURIComponent(`saved:${id}`)}`,
      { scroll: false },
    );
  }, [id, router]);

  return <LogoLoader label="Opening comparison…" showText />;
}
