"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getAdminToken, setAdminToken } from "@/lib/admin-api";

type NavItem = {
  href: string;
  label: string;
  desc: string;
  icon: "overview" | "tenants" | "usage" | "logs" | "llms";
};

const SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Platform",
    items: [
      { href: "/overview", label: "Overview", desc: "Funnel & health", icon: "overview" },
      { href: "/tenants", label: "Tenants", desc: "Accounts & listings", icon: "tenants" },
    ],
  },
  {
    title: "Operations",
    items: [
      { href: "/usage", label: "Usage", desc: "Tokens & metering", icon: "usage" },
      { href: "/logs", label: "Logs", desc: "Services & failures", icon: "logs" },
    ],
  },
  {
    title: "Intelligence",
    items: [{ href: "/llms", label: "LLMs", desc: "Providers & models", icon: "llms" }],
  },
];

function NavIcon({ name, active }: { name: NavItem["icon"]; active: boolean }) {
  const cls = `h-[16px] w-[16px] shrink-0 ${active ? "text-white" : "text-white/45 group-hover:text-white/70"}`;
  switch (name) {
    case "overview":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <rect x="3.5" y="3.5" width="7.5" height="7.5" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
          <rect x="13" y="3.5" width="7.5" height="7.5" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
          <rect x="3.5" y="13" width="7.5" height="7.5" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
          <rect x="13" y="13" width="7.5" height="7.5" rx="1.6" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      );
    case "tenants":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <circle cx="9" cy="8.2" r="3.2" stroke="currentColor" strokeWidth="1.6" />
          <path d="M3.2 18.2a5.2 5.2 0 0 1 11.6 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="17.2" cy="9.2" r="2.4" stroke="currentColor" strokeWidth="1.4" />
          <path d="M14.8 15.8a3.8 3.8 0 0 1 5.6 1.1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
        </svg>
      );
    case "usage":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <path d="M4 18V9" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M9.2 18V13.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M14.4 18V6.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
          <path d="M19.6 18V10.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
        </svg>
      );
    case "logs":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <rect x="3.5" y="4.2" width="17" height="15.6" rx="2" stroke="currentColor" strokeWidth="1.6" />
          <path d="M7.5 9h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <path d="M7.5 12.2h8.2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <path d="M7.5 15.4h5.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="17.2" cy="9" r="1" fill="currentColor" />
        </svg>
      );
    case "llms":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <path d="M12 3.2l1.6 4 4.2.4-3.1 2.7.9 4.1L12 12.1 8.4 14.4l.9-4.1L6.2 7.6l4.2-.4L12 3.2z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M5 14.5l.9 1.9 2 .4-1.5 1.3.4 2-1.8-1.1-1.8 1.1.4-2L2.1 16.8l2-.4.9-1.9z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
          <path d="M19 13.2l.7 1.4 1.5.3-1.1 1 .3 1.5-1.4-.8-1.4.8.3-1.5-1.1-1 1.5-.3.7-1.4z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
        </svg>
      );
  }
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getAdminToken()) router.replace("/login");
    else setReady(true);
  }, [router]);

  if (!ready) return null;

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <div className="flex h-screen overflow-hidden bg-[#f3f0ff]">
      {/* Sidebar: fixed visual, internal scroll */}
      <aside className="flex w-[256px] shrink-0 flex-col overflow-y-auto overscroll-contain border-r border-white/5 bg-[#15102e] [scrollbar-width:thin] [scrollbar-color:rgba(255,255,255,0.12)_transparent]">
        {/* Brand */}
        <div className="sticky top-0 z-10 bg-[#15102e] px-4 pb-3 pt-4">
          <div className="flex items-center gap-3">
            <img
              src="/Sayvors_Icon.png"
              alt="Sayvors"
              width={36}
              height={36}
              className="h-9 w-9 shrink-0 rounded-[6px] bg-white object-contain p-1 shadow-sm"
            />
            <div className="min-w-0">
              <p className="text-[14px] font-bold leading-none tracking-tight text-white">Sayvors</p>
              <p className="mt-0.5 text-[11px] font-medium leading-none text-white/45">Admin console</p>
            </div>
            <span className="ml-auto rounded-full border border-white/10 bg-white/[0.06] px-2 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-white/60">
              Admin
            </span>
          </div>
          <div className="mt-4 h-px bg-white/[0.06]" aria-hidden />
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-3" aria-label="Primary">
          <div className="space-y-5">
            {SECTIONS.map((section) => (
              <div key={section.title}>
                <p className="mb-1.5 px-2 text-[10px] font-bold uppercase tracking-[0.14em] text-white/30">{section.title}</p>
                <ul className="space-y-1">
                  {section.items.map((item) => {
                    const active = isActive(item.href);
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          aria-current={active ? "page" : undefined}
                          className={`group relative flex items-center gap-3 rounded-[6px] px-2.5 py-2.5 text-[13px] transition ${
                            active
                              ? "bg-white text-[#1e1547] shadow-sm"
                              : "text-white/55 hover:bg-white/[0.06] hover:text-white"
                          }`}
                        >
                          {/* active left bar for non-white active alternative: keep subtle */}
                          <NavIcon name={item.icon} active={active} />
                          <span className="min-w-0 flex-1">
                            <span className={`block text-[13px] font-semibold leading-none ${active ? "text-[#1e1547]" : "text-white/80 group-hover:text-white"}`}>
                              {item.label}
                            </span>
                            <span className={`block truncate text-[11px] leading-none ${active ? "mt-1 text-[#1e1547]/55" : "mt-1 text-white/35 group-hover:text-white/50"}`}>
                              {item.desc}
                            </span>
                          </span>
                          {active && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#1e1547]/20" aria-hidden />}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>

        </nav>

        {/* Footer */}
        <div className="sticky bottom-0 mt-auto bg-[#15102e] p-3">
          <div className="h-px bg-white/[0.06]" aria-hidden />
          <div className="mt-3 flex items-center gap-2 rounded-[6px] bg-white/[0.04] px-3 py-2.5 ring-1 ring-white/[0.06]">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/10 text-[11px] font-bold text-white/80">AD</div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[12px] font-semibold leading-none text-white">Admin</p>
              <p className="truncate text-[11px] leading-none text-white/40">Session · secure</p>
            </div>
            <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-400" aria-hidden title="Session active" />
          </div>
          <button
            onClick={() => {
              setAdminToken(null);
              router.replace("/login");
            }}
            className="mt-2 flex w-full items-center justify-center gap-2 rounded-[6px] border border-white/10 bg-transparent px-3 py-2.5 text-[12px] font-semibold text-white/60 transition hover:border-white/15 hover:bg-white/[0.06] hover:text-white"
          >
            <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" className="opacity-60">
              <path d="M15.2 18.2L9 12l6.2-6.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M9 12H21" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
              <path d="M3 5.2a2 2 0 0 1 2-2h6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M3 18.8a2 2 0 0 0 2 2h6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            Sign out
          </button>
          <p className="mt-2.5 text-center text-[10px] font-medium tracking-wide text-white/20">Sayvors · Admin v1 · Internal</p>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto overscroll-contain bg-[#f3f0ff] p-4 sm:p-6">{children}</main>
    </div>
  );
}
