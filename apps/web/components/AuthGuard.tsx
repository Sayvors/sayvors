"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { user, loading } = useAuth();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
    } else {
      setChecked(true);
    }
  }, [user, loading, router]);

  if (!checked) {
    return (
      <div className="flex h-screen items-center justify-center bg-fog dark:bg-ink">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-deep-violet border-t-transparent" />
          <p className="text-[12px] text-ink/40 dark:text-fog/40">Loading...</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
