"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getAdminToken, setAdminToken } from "@/lib/admin-api";

const NAV = [
  { href: "/overview", label: "Overview" },
  { href: "/tenants", label: "Tenants" },
  { href: "/logs", label: "Logs" },
  { href: "/llms", label: "LLMs" },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getAdminToken()) router.replace("/login");
    else setReady(true);
  }, [router]);

  if (!ready) return null;

  return (
    <div className="flex min-h-screen bg-[#f3f0ff]">
      <aside className="flex w-[200px] shrink-0 flex-col bg-[#1e1547] p-3">
        <p className="px-2 pb-3 pt-1 text-[14px] font-bold text-white">
          Sayvors <span className="rounded bg-white/10 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white/70">Admin</span>
        </p>
        <nav className="space-y-0.5">
          {NAV.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`block rounded-lg px-3 py-2 text-[13px] font-medium transition ${
                  active ? "bg-white/10 text-white" : "text-white/50 hover:bg-white/[0.06] hover:text-white"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <button
          onClick={() => {
            setAdminToken(null);
            router.replace("/login");
          }}
          className="mt-auto rounded-lg px-3 py-2 text-left text-[12px] font-semibold text-white/40 transition hover:bg-white/[0.06] hover:text-white"
        >
          Sign out
        </button>
      </aside>
      <main className="min-w-0 flex-1 p-4 sm:p-6">{children}</main>
    </div>
  );
}
