"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import LogoLoader from "@/components/LogoLoader";
import { adminMe } from "@/lib/api-admin";

/* Guards /admin/* (except /admin/login): no tenant session exists here —
 * platform operators authenticate with the separate admin password. */
export default function AdminGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ok, setOk] = useState(false);

  useEffect(() => {
    let cancelled = false;
    adminMe()
      .then(() => {
        if (!cancelled) setOk(true);
      })
      .catch(() => {
        if (!cancelled) router.replace("/admin/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (!ok) {
    return (
      <div className="flex h-screen items-center justify-center bg-fog dark:bg-ink">
        <LogoLoader size={48} />
      </div>
    );
  }
  return <>{children}</>;
}
