"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { adminLogout, checkAdminSession } from "@/lib/admin-api";
import { useTheme } from "../theme";

type NavItem = {
  href: string;
  label: string;
  desc: string;
  icon: "overview" | "tenants" | "usage" | "logs" | "llms" | "voice" | "embeddings";
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
    items: [
      { href: "/llms", label: "LLMs", desc: "Providers & models", icon: "llms" },
      { href: "/embeddings", label: "Embeddings", desc: "RAG vector API", icon: "embeddings" },
      { href: "/voice", label: "Voice models", desc: "WhatsApp voice TTS", icon: "voice" },
    ],
  },
];

const SIDEBAR_KEY = "sayvors-admin-sidebar";

function NavIcon({ name, active }: { name: NavItem["icon"]; active: boolean }) {
  const cls = `h-[16px] w-[16px] shrink-0 ${active ? "text-[var(--ui-ink)]" : "text-ink/45 group-hover:text-ink/75"}`;
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
        </svg>
      );
    case "voice":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <rect x="9" y="3" width="6" height="11.5" rx="3" stroke="currentColor" strokeWidth="1.6" />
          <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" stroke="currentColor" strokeWidth="1.6" />
          <path d="M12 18v3" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      );
    case "embeddings":
      return (
        <svg aria-hidden viewBox="0 0 24 24" fill="none" className={cls}>
          <circle cx="6" cy="6.5" r="2.2" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="18" cy="6.5" r="2.2" stroke="currentColor" strokeWidth="1.5" />
          <circle cx="12" cy="17.5" r="2.2" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M7.7 7.8l2.8 7.5M16.3 7.8l-2.8 7.5M8.2 6.5h7.6"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      );
    default:
      return null;
  }
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, toggle } = useTheme();
  const [ready, setReady] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    try {
      return localStorage.getItem(SIDEBAR_KEY) === "1";
    } catch {
      /* private mode */
    }
    return false;
  });
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    checkAdminSession().then((ok) => {
      if (!ok) router.replace("/login");
      else setReady(true);
    });
  }, [router]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  if (!ready) return null;

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  const nav = (
    <nav className="flex-1 px-3 py-3" aria-label="Primary">
      <div className="space-y-5">
        {SECTIONS.map((section) => (
          <div key={section.title}>
            <p className={`mb-1.5 px-2 text-[10px] font-bold uppercase tracking-[0.14em] text-ink/40 ${collapsed ? "text-center" : ""}`}>
              {collapsed ? "···" : section.title}
            </p>
            <ul className="space-y-1">
              {section.items.map((item) => {
                const active = isActive(item.href);
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      title={collapsed ? item.label : undefined}
                      className={`group relative flex items-center gap-3 rounded-[2px] px-2.5 py-2.5 text-[13px] transition-colors duration-150 ${
                        active
                          ? "bg-[var(--ui-sunken)] text-[var(--ui-ink)]"
                          : "text-ink/55 hover:bg-ink/[0.04] hover:text-ink"
                      } ${collapsed ? "justify-center px-0" : ""}`}
                    >
                      {/* The active marker is a rail, not a fill. */}
                      <span
                        aria-hidden
                        className={`absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 bg-[var(--ui-ink)] transition-opacity duration-150 ${
                          active ? "opacity-100" : "opacity-0"
                        }`}
                      />
                      <NavIcon name={item.icon} active={active} />
                      {!collapsed && (
                        <span className="min-w-0 flex-1">
                          <span className={`block text-[13px] font-semibold leading-none ${active ? "text-[var(--ui-ink)]" : "text-ink/80 group-hover:text-ink"}`}>
                            {item.label}
                          </span>
                          <span className={`mt-1 block truncate text-[11px] leading-none ${active ? "text-ink/55" : "text-ink/40 group-hover:text-ink/60"}`}>
                            {item.desc}
                          </span>
                        </span>
                      )}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </nav>
  );

  const header = (
    <header className="sticky top-0 z-20 flex items-center justify-between border-b border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-3">
      <div className="flex items-center gap-3">
        <Image
          src="/Sayvors_Icon.png"
          alt="Sayvors"
          width={24}
          height={24}
          className="h-6 w-6 rounded-[2px] border border-[var(--ui-line)] bg-white object-contain p-0.5"
          unoptimized
        />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-bold tracking-tight text-[var(--ui-ink)]">Sayvors Admin</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() => {
            // Settings placeholder
          }}
          title="Settings"
          className="flex h-8 w-8 items-center justify-center rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1.5 text-[11px] font-bold outline-none transition focus:border-[var(--ui-ink)] disabled:opacity-50 text-emerald-600"
        >
          <svg aria-hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15.4l-1.4 1.4a5.5 5.5 0 0 1-2.1 2.1l-1.4 1.4a5.5 5.5 0 0 1-2.1-2.1l1.4-1.4a5.5 5.5 0 0 1 2.1-2.1l1.4 1.4a5.5 5.5 0 0 1 2.1 2.1z" />
          </svg>
        </button>
        <button
          onClick={() => {
            // Tour placeholder
          }}
          title="Tour"
          className="flex h-8 w-8 items-center justify-center rounded-[2px] border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] px-2 py-1.5 text-[11px] font-bold outline-none transition focus:border-[var(--ui-ink)] disabled:opacity-50 text-emerald-600"
        >
          <svg aria-hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M12 15.4l-4.5 4.5L3 15.4l2.7-2.7a10 10 0 0 1 1.4-2.1l1.4-1.4a5.5 5.5 0 0 1 2.1-2.1l1.4 1.4a5.5 5.5 0 0 1 2.1 2.1z" />
          </svg>
        </button>
        <div className="flex items-center gap-2 rounded-[2px] border border-[var(--ui-line)] px-3 py-2.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-deep-violet text-[11px] font-bold text-white">AD</div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[12px] font-semibold leading-none text-[var(--ui-ink)]">Admin</p>
            <p className="truncate text-[11px] leading-none text-ink/40">Session · secure</p>
          </div>
          <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" aria-hidden title="Session active" />
        </div>
        <button
          onClick={() => {
            adminLogout().finally(() => router.replace("/login"));
          }}
          title="Sign out"
          className="flex flex-1 items-center justify-center gap-2 rounded-[2px] border border-[var(--ui-line-strong)] px-3 py-2.5 text-[12px] font-semibold text-ink/60 transition-colors duration-150 hover:border-[var(--ui-ink)] hover:text-ink"
        >
          <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" className="opacity-60">
            <path d="M15.2 18.2L9 12l6.2-6.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
            <path d="M9 12H21" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            <path d="M3 5.2a2 2 0 0 1 2-2h6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            <path d="M3 18.8a2 2 0 0 0 2 2h6.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          Sign out
        </button>
      </div>
    </header>
  );

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--ui-page)]">
      {/* Sidebar: a drawer under lg, a flat rail on desktop. */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex flex-col border-r border-[var(--ui-line)] bg-[var(--ui-surface)] transition-[width,transform] duration-200 ease-out lg:static lg:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        } ${collapsed ? "lg:w-14" : "w-60"}`}
      >
        {/* Everything scrolls in here; the aside itself must not clip, or the
            collapse toggle straddling its right edge gets cut off. */}
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain [scrollbar-width:thin]">
        {/* Brand */}
        <div className="sticky top-0 z-10 bg-[var(--ui-surface)] px-4 pb-3 pt-4">
          <div className={`flex items-center gap-3 ${collapsed ? "lg:justify-center lg:px-0" : ""}`}>
            <Image
              src="/Sayvors_Icon.png"
              alt="Sayvors"
              width={36}
              height={36}
              className="h-9 w-9 shrink-0 rounded-[2px] border border-[var(--ui-line)] bg-white object-contain p-1"
              unoptimized
            />
            {!collapsed && (
              <div className="min-w-0">
                <p className="text-[14px] font-bold leading-none tracking-tight text-[var(--ui-ink)]">Sayvors</p>
                <p className="mt-0.5 text-[11px] font-medium leading-none text-ink/45">Admin console</p>
              </div>
            )}
            {!collapsed && (
              <span className="ml-auto rounded-[2px] border border-[var(--ui-line)] px-2 py-1 text-[9px] font-bold uppercase tracking-[0.14em] text-ink/50">
                Admin
              </span>
            )}
          </div>
          <div className="mt-4 h-px bg-[var(--ui-line)]" aria-hidden />
        </div>

        {nav}
        </div>

        {/* Collapse toggle: a small circular arrow straddling the sidebar's
            right edge line. Desktop only. */}
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className="absolute -right-3 top-[68px] z-50 hidden h-6 w-6 items-center justify-center rounded-full border border-[var(--ui-line-strong)] bg-[var(--ui-surface)] text-[var(--ui-ink)] transition-colors duration-150 hover:bg-[var(--ui-sunken)] lg:flex"
        >
          <svg aria-hidden viewBox="0 0 24 24" fill="none" className={`h-3 w-3 transition-transform duration-200 ${collapsed ? "rotate-180" : ""}`}>
            <path d="M14.5 6.5L9 12l5.5 5.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </aside>

      {/* Desktop header */}
      {header}

      {/* Mobile scrim */}
      {navOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={() => setNavOpen(false)}
          className="fixed inset-0 z-30 bg-ink/30 lg:hidden"
        />
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-[var(--ui-line)] bg-[var(--ui-surface)] px-4 py-3 lg:hidden">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            aria-label="Open navigation"
            aria-expanded={navOpen}
            className="flex h-8 w-8 items-center justify-center rounded-[2px] border border-[var(--ui-line-strong)] text-ink/60"
          >
            <svg aria-hidden viewBox="0 0 24 24" fill="none" className="h-4 w-4">
              <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
            </svg>
          </button>
          <Image src="/Sayvors_Icon.png" alt="Sayvors" width={24} height={24} className="h-6 w-6 rounded-[2px] border border-[var(--ui-line)] bg-white object-contain p-0.5" unoptimized />
          <p className="text-[13px] font-bold tracking-tight text-[var(--ui-ink)]">Sayvors Admin</p>
        </header>

        <main className="min-w-0 flex-1 overflow-y-auto overscroll-contain bg-[var(--ui-page)] p-4 sm:p-6">{children}</main>
      </div>
    </div>
  );
}