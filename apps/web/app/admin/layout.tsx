"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { adminClearToken, adminGetToken } from "@/lib/admin-api";

const TABS = [
  { href: "/admin/overview", label: "Overview" },
  { href: "/admin/tenants", label: "Tenants" },
  { href: "/admin/models", label: "AI Models" },
  { href: "/admin/health", label: "Health" },
  { href: "/admin/catalogs", label: "Catalogs" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    setHasToken(!!adminGetToken());
    setReady(true);
  }, []);

  // Re-check on every navigation (login page sets the token).
  useEffect(() => {
    setHasToken(!!adminGetToken());
  }, [pathname]);

  if (!ready) {
    return <div className="flex min-h-screen items-center justify-center bg-[#f4f1ff] text-[13px] text-ink/40">Loading…</div>;
  }

  if (!hasToken) {
    // The login form lives at /admin; every other admin page redirects there.
    if (pathname === "/admin") return <>{children}</>;
    router.replace("/admin");
    return <div className="flex min-h-screen items-center justify-center bg-[#f4f1ff] text-[13px] text-ink/40">Redirecting to login…</div>;
  }

  return (
    <div className="min-h-screen bg-[#f4f1ff]">
      <header className="border-b border-deep-violet/10 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
          <span className="text-[15px] font-bold text-ink">
            Sayvors <span className="text-deep-violet">Admin</span>
          </span>
          <nav className="flex flex-wrap items-center gap-1">
            {TABS.map((t) => {
              const active = pathname.startsWith(t.href);
              return (
                <Link
                  key={t.href}
                  href={t.href}
                  className={`rounded-lg px-3 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${active ? "bg-deep-violet/[0.08] text-deep-violet" : "text-ink/50 hover:bg-ink/[0.04] hover:text-ink"}`}
                >
                  {t.label}
                </Link>
              );
            })}
          </nav>
          <button
            onClick={() => {
              adminClearToken();
              setHasToken(false);
              router.replace("/admin");
            }}
            className="ml-auto rounded-lg border border-ink/10 px-3 py-1.5 text-[12px] font-semibold text-ink/50 outline-none transition hover:border-coral/40 hover:text-coral focus-visible:ring-2 focus-visible:ring-coral/30"
          >
            Log out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
