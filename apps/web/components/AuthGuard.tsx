"use client";

import { useRouter, usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import LogoLoader from "@/components/LogoLoader";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, loading } = useAuth();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace("/login");
    } else if (!user.onboarded && !pathname.startsWith("/onboarding")) {
      router.replace("/onboarding");
    } else {
      setChecked(true);
    }
  }, [user, loading, router, pathname]);

  if (!checked) {
    return (
      <div className="flex h-screen items-center justify-center bg-fog dark:bg-ink">
        <LogoLoader size={48} label="Loading…" showText />
      </div>
    );
  }

  return <>{children}</>;
}
