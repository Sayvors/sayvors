"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { checkAdminSession } from "@/lib/admin-api";

export default function AdminRootPage() {
  const router = useRouter();
  useEffect(() => {
    checkAdminSession().then((ok) => {
      router.replace(ok ? "/overview" : "/login");
    });
  }, [router]);
  return null;
}
