"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { NAV_DRAWER_EVENTS } from "@/lib/tour/nav-drawer";
import { visibleChannelNav, type ChannelNavRow } from "@/lib/channel-nav";

interface NavItem {
  key: string;
  icon: React.ReactNode;
  href: string;
}

// The everyday surfaces. Channels is expandable (Inbox + per-network manage)
// and rendered separately below so it can hold children.
const MAIN_ITEMS: NavItem[] = [
  { key: "dashboard", icon: <LayoutIcon />, href: "/dashboard" },
  { key: "analytics", icon: <ChartIcon />, href: "/dashboard/analytics" },
  { key: "locations", icon: <LocationIcon />, href: "/dashboard/locations" },
  { key: "services", icon: <WrenchIcon />, href: "/dashboard/services" },
  { key: "postsMedia", icon: <MegaphoneIcon />, href: "/dashboard/posts-media" },
  { key: "reviews", icon: <StarIcon />, href: "/dashboard/reviews" },
  { key: "databank", icon: <DatabaseIcon />, href: "/dashboard/databank" },
];

const ADVANCED_ITEMS: NavItem[] = [
  { key: "outbox", icon: <OutboxIcon />, href: "/dashboard/outbox" },
  { key: "notifications", icon: <BellIcon />, href: "/dashboard/notifications" },
  { key: "insights", icon: <BulbIcon />, href: "/dashboard/insights" },
  { key: "growth", icon: <TrendingIcon />, href: "/dashboard/growth" },
  { key: "benchmark", icon: <TrophyIcon />, href: "/dashboard/benchmark" },
  { key: "issues", icon: <ChecklistIcon />, href: "/dashboard/issues" },
  { key: "verification", icon: <ShieldCheckIcon />, href: "/dashboard/verification" },
  { key: "usage", icon: <GaugeIcon />, href: "/dashboard/usage" },
  { key: "billing", icon: <CardIcon />, href: "/dashboard/billing" },
  { key: "profile", icon: <UserIcon />, href: "/dashboard/profile" },
  { key: "team", icon: <TeamIcon />, href: "/dashboard/team" },
  { key: "settings", icon: <GearIcon />, href: "/dashboard/settings" },
];

const ADVANCED_OPEN_KEY = "sayvors.sidebar.advanced-open";

function isActive(pathname: string, item: NavItem) {
  const { href } = item;
  if (href === "/dashboard") return pathname === "/dashboard";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  // Small screens get the nav as an overlay drawer, not a column. A 220px
  // inline sidebar is 56% of a 390px phone, permanently, before any content.
  const [isMobile, setIsMobile] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [teamContext, setTeamContext] = useState<{ permissions?: string[]; role_name?: string } | null>(null);
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch("/api/v1/team/context", { credentials: "include" });
        if (res.ok) setTeamContext(await res.json());
      } catch {
        /* not authenticated — item hidden */
      }
    })();
  }, []);

  const teamPermitted = teamContext && (teamContext.permissions || []).some((p: string) => ["team.manage", "team.view"].includes(p));
  const filteredAdvanced = ADVANCED_ITEMS.filter((item) => item.key !== "team" || teamPermitted);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const apply = () => {
      setIsMobile(mq.matches);
      // Leaving the mobile breakpoint should not strand a half-open drawer,
      // and entering it should not leave the inline toggle in a stale state.
      if (!mq.matches) setDrawerOpen(false);
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);

  // While the drawer is open it covers the page, so the page behind it must
  // not scroll away underneath.
  useEffect(() => {
    if (!drawerOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [drawerOpen]);

  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDrawerOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  // The guided tour points at nav items. On a phone those live in the drawer,
  // so the tour asks for it to open rather than spotlighting something the
  // user cannot see. No-op on desktop, where the nav is already inline. An
  // item the tour targets may sit inside the collapsed Advanced section, so
  // opening also unfolds it.
  useEffect(() => {
    const onOpen = () => {
      if (isMobile) setDrawerOpen(true);
      setAdvancedOpen(true);
    };
    const onClose = () => setDrawerOpen(false);
    window.addEventListener(NAV_DRAWER_EVENTS.OPEN, onOpen);
    window.addEventListener(NAV_DRAWER_EVENTS.CLOSE, onClose);
    return () => {
      window.removeEventListener(NAV_DRAWER_EVENTS.OPEN, onOpen);
      window.removeEventListener(NAV_DRAWER_EVENTS.CLOSE, onClose);
    };
  }, [isMobile]);
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const { t, dir } = useI18n();
  const menuRef = useRef<HTMLDivElement>(null);

  const displayName =
    user && (user.first_name || user.last_name)
      ? `${user.first_name} ${user.last_name}`.trim()
      : t.account.fallbackName;

  const initials = user
    ? `${user.first_name?.[0] ?? ""}${user.last_name?.[0] ?? ""}`.toUpperCase() || "U"
    : "U";

  // Remember the Advanced choice, then surface it anyway when the user is on
  // an Advanced page — a collapsed section hiding the active item reads as a
  // broken highlight.
  useEffect(() => {
    // Restore after mount so SSR and client render agree.
    try {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is an external store; reading it during render would break SSR
      if (localStorage.getItem(ADVANCED_OPEN_KEY) === "1") setAdvancedOpen(true);
    } catch {
      /* storage unavailable */
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a nav highlight hidden under a closed section reads as broken
    if (filteredAdvanced.some((item) => isActive(pathname, item))) setAdvancedOpen(true);
  }, [pathname]);

  const toggleAdvanced = () => {
    setAdvancedOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(ADVANCED_OPEN_KEY, next ? "1" : "0");
      } catch {
        /* storage unavailable */
      }
      return next;
    });
  };

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handleClick);
      document.removeEventListener("keydown", handleKey);
    };
  }, []);

  useEffect(() => {
    setMenuOpen(false);
    // Following a link inside the drawer should reveal the page, not leave the
    // nav covering it.
    setDrawerOpen(false);
  }, [pathname]);

  // "Rail" means the icon-only 56px strip. Only the inline desktop sidebar can
  // be a rail — the mobile drawer is always full width, so gating label
  // visibility on `collapsed` alone would render it icon-only for no reason.
  const rail = collapsed && !isMobile;

  const labelFor = (item: NavItem) =>
    (t.nav as Record<string, string>)[item.key] ?? item.key;

  return (
    <>
      {/* Hamburger — mobile only, fixed so it does not shift page content.
          Vertically centered inside the 48px header (top-1 + h-10 = 4+40+4). */}
      <button
        onClick={() => setDrawerOpen(true)}
        aria-label={t.nav.openMenu}
        aria-expanded={drawerOpen}
        aria-controls="dashboard-sidebar"
        className={`fixed ${dir === "rtl" ? "right-1" : "left-1"} top-1 z-40 flex h-10 w-10 items-center justify-center rounded-xl border border-ink/[0.08] bg-white text-ink shadow-lg transition hover:bg-fog focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:border-white/10 dark:bg-[#1e1547] dark:text-white dark:hover:bg-[#251b55] md:hidden ${
          drawerOpen ? "pointer-events-none opacity-0" : "opacity-100"
        }`}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-5 w-5">
          <path d="M4 7h16M4 12h16M4 17h16" />
        </svg>
      </button>

      {/* Scrim — tap anywhere to dismiss, as a drawer is expected to do. */}
      {drawerOpen && (
        <button
          onClick={() => setDrawerOpen(false)}
          aria-label={t.nav.closeMenu}
          tabIndex={-1}
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
        />
      )}

      <aside
        id="dashboard-sidebar"
        aria-hidden={isMobile && !drawerOpen ? true : undefined}
        className={`flex h-screen flex-col ${dir === "rtl" ? "border-l" : "border-r"} border-ink/[0.06] bg-white transition-all duration-200 dark:border-fog/[0.08] dark:bg-[#151030] ${
          isMobile
            ? `fixed inset-y-0 ${dir === "rtl" ? "right-0" : "left-0"} z-50 w-[248px] shadow-2xl ${
                drawerOpen ? "translate-x-0" : dir === "rtl" ? "translate-x-full" : "-translate-x-full"
              }`
            : collapsed
              ? "w-[56px]"
              : "w-[220px]"
        }`}
      >
      {/* Logo */}
      <div className="flex h-12 items-center gap-2 border-b border-ink/[0.05] px-3 dark:border-fog/[0.06]">
        <Image src="/Sayvors_Icon.png" alt="" width={28} height={20} className="h-5 w-auto" />
        {/* The drawer is always wide, so the wordmark shows even when the
            inline rail is collapsed. Dark wordmark = white, for the dark theme. */}
        {(!collapsed || isMobile) && (
          <>
            <Image src="/Sayvors_Wordmark_Light.png" alt="Sayvors" width={110} height={18} className="h-4 w-auto dark:hidden" />
            <Image src="/Sayvors_Wordmark_Dark.png" alt="Sayvors" width={110} height={18} className="hidden h-4 w-auto dark:block" />
          </>
        )}
        <button
          onClick={() => setDrawerOpen(false)}
          aria-label={t.nav.closeMenu}
          className="ml-auto flex h-7 w-7 items-center justify-center rounded-md text-ink/30 outline-none transition hover:bg-ink/[0.05] hover:text-ink/60 focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-fog/40 dark:hover:bg-fog/[0.08] dark:hover:text-fog/70 md:hidden"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" className="h-4 w-4">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 pt-3 pb-4" aria-label={t.nav.mainNavigation}>
        <div className="space-y-0.5">
          {MAIN_ITEMS.slice(0, 3).map((item) => (
            <NavRow key={item.href} item={item} active={isActive(pathname, item)} rail={rail} dir={dir} label={labelFor(item)} />
          ))}
        </div>
        <ChannelsNav pathname={pathname} rail={rail} dir={dir} labels={t.nav as unknown as Record<string, string>} />
        <div className="mt-0.5 space-y-0.5">
          {MAIN_ITEMS.slice(3).map((item) => (
            <NavRow key={item.href} item={item} active={isActive(pathname, item)} rail={rail} dir={dir} label={labelFor(item)} />
          ))}
        </div>

        {/* Advanced — the long tail, folded away by default. */}
        <div className="mt-3 border-t border-ink/[0.05] pt-3 dark:border-fog/[0.06]">
          <button
            onClick={toggleAdvanced}
            aria-expanded={advancedOpen}
            title={rail ? t.nav.advanced : undefined}
            className={`flex w-full items-center rounded-lg px-2.5 py-2 text-ink/35 outline-none transition hover:bg-ink/[0.04] hover:text-ink/60 focus-visible:ring-2 focus-visible:ring-deep-violet/30 dark:text-fog/35 dark:hover:bg-fog/[0.06] dark:hover:text-fog/60 ${
              rail ? "justify-center" : "gap-2"
            }`}
          >
            {!rail && (
              <span className="flex-1 text-start text-[10px] font-semibold uppercase tracking-widest">
                {t.nav.advanced}
              </span>
            )}
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              aria-hidden
              className={`h-3.5 w-3.5 shrink-0 transition-transform ${advancedOpen ? "rotate-180" : ""}`}
            >
              <path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          {advancedOpen && (
            <div className="mt-0.5 space-y-0.5">
              {filteredAdvanced.map((item) => (
                <NavRow key={item.href} item={item} active={isActive(pathname, item)} rail={rail} dir={dir} label={labelFor(item)} />
              ))}
            </div>
          )}
        </div>
      </nav>

      {/* Account + collapse */}
      <div ref={menuRef} className="relative border-t border-ink/[0.05] dark:border-fog/[0.06]">
        {menuOpen && (
          <div
            className={`absolute bottom-full z-50 mb-2 overflow-hidden rounded-xl border border-ink/[0.08] bg-white shadow-xl dark:border-fog/[0.08] dark:bg-[#221b4d] ${
              rail ? (dir === "rtl" ? "right-12 w-48" : "left-12 w-48") : "inset-x-2"
            }`}
          >
            <div className="border-b border-ink/[0.06] px-3 py-2.5 dark:border-fog/[0.08]">
              <p className="truncate text-[13px] font-medium text-ink dark:text-white">
                {displayName}
              </p>
              <p className="truncate text-[11px] text-ink/40 dark:text-fog/40">{user?.email ?? ""}</p>
            </div>
            <div className="py-1">
              <SidebarMenuLink href="/dashboard/profile" label={t.account.myProfile} />
              <SidebarMenuLink href="/dashboard/settings" label={t.account.settings} />
            </div>
            <div className="border-t border-ink/[0.06] py-1 dark:border-fog/[0.08]">
              <button
                onClick={() => logout()}
                className="flex w-full items-center px-3 py-2 text-[12px] text-coral transition hover:bg-coral/[0.07]"
              >
                {t.account.signOut}
              </button>
            </div>
          </div>
        )}
        <div className={`flex items-center gap-1 p-2 ${collapsed && !isMobile ? "flex-col" : ""}`}>
          <button
            onClick={() => (isMobile ? setDrawerOpen(false) : setMenuOpen(!menuOpen))}
            aria-label={isMobile ? t.nav.closeMenu : t.account.menu}
            aria-expanded={isMobile ? drawerOpen : menuOpen}
            title={!isMobile && collapsed ? displayName : undefined}
            className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1.5 outline-none transition hover:bg-ink/[0.04] focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:hover:bg-fog/[0.06] ${
              collapsed ? "justify-center" : ""
            }`}
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-violet-light to-magenta text-[10px] font-semibold text-white">
              {initials}
            </span>
            {!collapsed && (
              <span className="min-w-0 flex-1 text-start">
                <span className="block truncate text-[12px] font-medium text-ink dark:text-fog">
                  {displayName}
                </span>
                <span className="block truncate text-[10px] text-ink/40 dark:text-fog/40">
                  {user?.email ?? ""}
                </span>
              </span>
            )}
          </button>
          <button
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? t.nav.expand : t.nav.collapse}
            title={collapsed ? t.nav.expand : t.nav.collapse}
            /* The drawer is already the compact form on a phone — a collapse
               toggle there would collapse what is off-screen twice over. */
            className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-md text-ink/25 outline-none transition hover:bg-ink/[0.05] hover:text-ink/50 focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-fog/25 dark:hover:bg-fog/[0.08] dark:hover:text-fog/50 md:flex"
          >
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              className={`h-3.5 w-3.5 transition-transform ${collapsed ? "rotate-180" : ""}`}
            >
              <path d="M10 3L5 8l5 5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </aside>
    </>
  );
}

function NavRow({
  item,
  active,
  rail,
  dir,
  label,
}: {
  item: NavItem;
  active: boolean;
  rail: boolean;
  dir: "ltr" | "rtl";
  label: string;
}) {
  return (
    <Link
      href={item.href}
      data-tour={`nav-${item.key}`}
      aria-current={active ? "page" : undefined}
      title={rail ? label : undefined}
      className={`group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/30 ${
        active
          ? "bg-deep-violet/[0.07] text-deep-violet dark:bg-violet-light/[0.14] dark:text-violet-soft"
          : "text-ink/55 hover:bg-ink/[0.04] hover:text-ink dark:text-fog/50 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
      }`}
    >
      <span
        aria-hidden
        className={`absolute ${dir === "rtl" ? "right-0 rounded-l-full" : "left-0 rounded-r-full"} top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-deep-violet transition-opacity dark:bg-violet-light ${
          active ? "opacity-100" : "opacity-0"
        }`}
      />
      <span
        className={`h-4 w-4 shrink-0 transition-colors ${
          active
            ? "text-deep-violet dark:text-violet-soft"
            : "text-ink/30 group-hover:text-ink/60 dark:text-fog/30 dark:group-hover:text-fog/60"
        }`}
      >
        {item.icon}
      </span>
      {!rail && <span className="flex-1 truncate">{label}</span>}
    </Link>
  );
}

function ChannelsNav({
  pathname,
  rail,
  dir,
  labels,
}: {
  pathname: string;
  rail: boolean;
  dir: "ltr" | "rtl";
  labels: Record<string, string>;
}) {
  const [open, setOpen] = useState(true);
  const [rows, setRows] = useState<ChannelNavRow[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { apiFetch } = await import("@/lib/api-rag");
        const [ch, meta] = await Promise.all([
          apiFetch("/api/v1/channels?limit=100").catch(() => ({ channels: [] })),
          apiFetch("/api/v1/meta/connections").catch(() => ({ connections: [] })),
        ]);
        if (cancelled) return;
        const list = (ch?.channels ?? []) as { platform: string }[];
        const conns = (meta?.connections ?? []) as { provider: string; status: string }[];
        setRows(visibleChannelNav(list, conns));
      } catch {
        if (!cancelled) setRows((prev) => prev ?? [{ key: "connect" }]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (pathname.startsWith("/dashboard/channels") || pathname.startsWith("/dashboard/inbox")) setOpen(true);
  }, [pathname]);

  const activeParent = pathname.startsWith("/dashboard/channels") || pathname.startsWith("/dashboard/inbox");
  const hrefFor = (k: ChannelNavRow["key"]) =>
    k === "inbox" ? "/dashboard/channels/inbox" : k === "overview" ? "/dashboard/channels" : k === "connect" ? "/dashboard/channels" : `/dashboard/channels/${k}`;
  const labelFor = (k: ChannelNavRow["key"]) =>
    k === "inbox" ? labels.inbox ?? "Inbox" : k === "overview" ? labels.connectMore ?? "Connect more" : k === "connect" ? labels.connectChannel ?? "Connect a channel" : k[0].toUpperCase() + k.slice(1);

  return (
    <div className="mt-0.5">
      <div
        className={`group relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/30 ${
          activeParent ? "bg-deep-violet/[0.07] text-deep-violet" : "text-ink/55 hover:bg-ink/[0.04]"
        }`}
      >
        <Link href="/dashboard/channels/inbox" data-tour="nav-channels" className="flex min-w-0 flex-1 items-center gap-2.5">
          <span className="h-4 w-4 shrink-0">💬</span>
          {!rail && <span className="flex-1 truncate">{labels.channels ?? "Channels"}</span>}
        </Link>
        {!rail && (
          <button onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-label="Toggle channels" className="rounded px-1 text-ink/40 hover:text-ink">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`}><path d="M4 6l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" /></svg>
          </button>
        )}
      </div>
      {open && !rail && (
        <div className="ml-6 mt-0.5 space-y-0.5 border-l border-ink/[0.06] pl-2">
          {!rows && (
            <>
              <div className="h-7 animate-pulse rounded-md bg-ink/[0.05]" />
              <div className="h-7 animate-pulse rounded-md bg-ink/[0.05]" />
            </>
          )}
          {rows?.map((r) =>
            r.key === "overview" ? (
              <Link key="overview" href="/dashboard/channels" className="block rounded-md px-2 py-1.5 text-[12px] font-semibold text-deep-violet hover:bg-deep-violet/[0.06]">
                ＋ {labelFor("overview")}
              </Link>
            ) : r.key === "connect" ? (
              <Link key="connect" href="/dashboard/channels" data-tour="nav-channels-connect" className="block rounded-md bg-deep-violet/[0.07] px-2 py-1.5 text-[12px] font-semibold text-deep-violet hover:bg-deep-violet/[0.1]">
                ＋ {labelFor("connect")}
              </Link>
            ) : (
              <Link
                key={r.key}
                href={hrefFor(r.key)}
                data-tour={`nav-channels-${r.key}`}
                aria-current={pathname === hrefFor(r.key) ? "page" : undefined}
                className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-[12px] font-medium transition hover:bg-ink/[0.04] ${pathname === hrefFor(r.key) ? "bg-deep-violet/[0.07] text-deep-violet" : "text-ink/60"}`}
              >
                {r.key === "inbox" ? "✉️" : r.key === "whatsapp" ? "💬" : r.key === "instagram" ? "📸" : "👤"}
                <span className="flex-1 truncate">{labelFor(r.key)}</span>
                {r.key !== "inbox" && <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" title="connected" />}
              </Link>
            )
          )}
          {rows && rows.some((r) => r.key !== "connect" && r.key !== "inbox" && r.key !== "overview") && (
            <p className="px-2 pt-1 text-[10px] font-semibold uppercase tracking-widest text-ink/30">{labels.manage ?? "Manage"}</p>
          )}
        </div>
      )}
    </div>
  );
}

function SidebarMenuLink({ href, label }: { href: string; label: string }) {
  return (
    <Link
      href={href}
      className="flex w-full items-center px-3 py-2 text-[12px] text-ink/60 transition hover:bg-ink/[0.04] hover:text-ink dark:text-fog/60 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
    >
      {label}
    </Link>
  );
}

/* ── Icons ─────────────────────────────────────── */

function LayoutIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

function LocationIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

function WrenchIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
    </svg>
  );
}

function MegaphoneIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11l18-5v12L3 13v-2z" />
      <path d="M11.6 16.8a3 3 0 11-5.8-1.6" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  );
}

function ChecklistIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="M3.5 6l1.2 1.2L7 4.9" />
      <path d="M3.5 12l1.2 1.2L7 10.9" />
      <path d="M3.5 18l1.2 1.2L7 16.9" />
    </svg>
  );
}

function ShieldCheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 20V10" /><path d="M12 20V4" /><path d="M6 20v-6" />
    </svg>
  );
}

function InboxIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 12h5l2 3h4l2-3h5" />
      <path d="M5.5 5h13l2.5 7v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6l2.5-7z" />
    </svg>
  );
}

function DatabaseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  );
}

function LinkIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" />
      <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" />
    </svg>
  );
}

function OutboxIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6" />
      <path d="M12 3v12" />
      <path d="M8 7l4-4 4 4" />
    </svg>
  );
}

function CardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20" />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8a6 6 0 00-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.7 21a2 2 0 01-3.4 0" />
    </svg>
  );
}

function ZapIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  );
}

function BulbIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 18h6" />
      <path d="M10 22h4" />
      <path d="M12 2a7 7 0 00-4 12.7c.6.5 1 1.4 1 2.3h6c0-.9.4-1.8 1-2.3A7 7 0 0012 2z" />
    </svg>
  );
}

function TrendingIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 6 13.5 15.5 8.5 10.5 1 18" />
      <polyline points="17 6 23 6 23 12" />
    </svg>
  );
}

function TrophyIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9H4.5a2.5 2.5 0 010-5H6" />
      <path d="M18 9h1.5a2.5 2.5 0 000-5H18" />
      <path d="M4 22h16" />
      <path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" />
      <path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" />
      <path d="M18 2H6v7a6 6 0 0012 0V2z" />
    </svg>
  );
}

function GaugeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 15l3.5-3.5" />
      <path d="M20.3 18a9.5 9.5 0 10-16.6 0" />
      <circle cx="12" cy="15" r="1" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

function TeamIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 00-3-3.87" />
      <path d="M16 3.13a4 4 0 010 7.75" />
    </svg>
  );
}

function GearIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" />
    </svg>
  );
}