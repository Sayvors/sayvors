"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getAdminToken } from "@/lib/admin-api";

export default function AdminRootPage() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getAdminToken() ? "/overview" : "/login");
  }, [router]);
  return null;
}
