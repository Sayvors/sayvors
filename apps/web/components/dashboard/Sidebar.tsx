"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { NAV_DRAWER_EVENTS } from "@/lib/tour/nav-drawer";
import { visibleChannelNav, type ChannelNavRow } from "@/lib/channel-nav";
import { getBudget, type Budget } from "@/lib/api-billing";

interface NavItem {
  key: string;
  icon: React.ReactNode;
  href: string;
}

// The everyday surfaces. Channels is expandable (Inbox + per-network manage)
// and rendered separately below so it can hold children.
const MAIN_ITEMS: NavItem[] = [
  { key: "dashboard", icon: <DashboardIcon />, href: "/dashboard" },
  { key: "analytics", icon: <AnalyticsIcon />, href: "/dashboard/analytics" },
  { key: "locations", icon: <PinIcon />, href: "/dashboard/locations" },
  { key: "postsMedia", icon: <PhotoIcon />, href: "/dashboard/posts-media" },
  { key: "customers", icon: <UsersIcon />, href: "/dashboard/customers" },
  { key: "reviews", icon: <StarIcon />, href: "/dashboard/reviews" },
  { key: "databank", icon: <DatabaseIcon />, href: "/dashboard/databank" },
  { key: "catalog", icon: <CatalogIcon />, href: "/dashboard/catalog" },
];

const ADVANCED_ITEMS: NavItem[] = [
  { key: "outbox", icon: <OutboxIcon />, href: "/dashboard/outbox" },
  { key: "issues", icon: <ChecklistIcon />, href: "/dashboard/issues" },
  { key: "verification", icon: <ShieldCheckIcon />, href: "/dashboard/verification" },
  { key: "usage", icon: <GaugeIcon />, href: "/dashboard/usage" },
  { key: "billing", icon: <CardIcon />, href: "/dashboard/billing" },
  { key: "plans", icon: <CardIcon />, href: "/dashboard/plans" },
];

function isActive(pathname: string, item: NavItem) {
  const { href } = item;
  if (href === "/dashboard") return pathname === "/dashboard";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  // Small screens get the nav as an overlay drawer, not a column. A 220px
  // inline sidebar is 56% of a 390px phone, permanently, before any content.
  const [isMobile, setIsMobile] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Folded by default; opens on click and closes again on any nav click.
  const [advancedOpen, setAdvancedOpen] = useState(false);

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

  // Listen for external open-drawer requests (e.g. from Header hamburger).
  useEffect(() => {
    const handler = () => setDrawerOpen(true);
    window.addEventListener("open-nav-drawer", handler);
    return () => window.removeEventListener("open-nav-drawer", handler);
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
  const { t, dir } = useI18n();

  const toggleAdvanced = () => setAdvancedOpen((prev) => !prev);

  useEffect(() => {
    // Following a link inside the drawer should reveal the page, not leave the
    // nav covering it.
    setDrawerOpen(false);
    // Any page change folds Advanced again — it only stays open while the
    // user is browsing it.
    setAdvancedOpen(false);
  }, [pathname]);

  // "Rail" means the icon-only strip. Only the inline desktop sidebar can be
  // a rail — the mobile drawer is always full width, so gating label
  // visibility on `collapsed` alone would render it icon-only for no reason.
  const rail = collapsed && !isMobile;

  const labelFor = (item: NavItem) =>
    (t.nav as Record<string, string>)[item.key] ?? item.key;

  return (
    <>
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
        className={`flex shrink-0 flex-col overflow-hidden bg-white text-ink ring-1 ring-ink/[0.06] transition-all duration-200 dark:bg-[#1d1636] dark:text-fog dark:ring-white/[0.08] ${
          isMobile
            ? `fixed inset-y-2 start-2 z-50 w-[264px] rounded-[20px] shadow-2xl ${
                drawerOpen ? "translate-x-0" : dir === "rtl" ? "translate-x-[calc(100%+8px)]" : "-translate-x-[calc(100%+8px)]"
              }`
            : `my-2 ms-2 h-[calc(100vh-1rem)] rounded-[20px] shadow-[0_18px_44px_-34px_rgba(26,18,48,0.45)] dark:shadow-none ${collapsed ? "w-[64px]" : "w-[236px]"}`
        }`}
      >
        {/* Brand. The rail is always dark, so the light-on-dark wordmark is
            used in both themes. */}
        <div className={`flex h-14 shrink-0 items-center ${rail ? "justify-center" : "gap-2.5 px-4"}`}>
          {rail ? (
            <Link
              href="/dashboard"
              aria-label="Sayvors"
              className="rounded-[6px] outline-none focus-visible:ring-2 focus-visible:ring-violet-soft/70"
            >
              <Image src="/Sayvors_Icon.png" alt="" width={28} height={20} className="h-6 w-auto" />
            </Link>
          ) : (
            <>
              {/* The lockup keeps its icon-then-wordmark order in RTL too —
                  brand marks do not mirror with the reading direction. */}
              <Link
                href="/dashboard"
                aria-label="Sayvors"
                dir="ltr"
                className="flex items-center gap-2.5 rounded-[6px] outline-none focus-visible:ring-2 focus-visible:ring-violet-soft/70"
              >
                <Image src="/Sayvors_Icon.png" alt="" width={28} height={20} className="h-6 w-auto" />
                <Image
                  src="/Sayvors_Wordmark_Light.png"
                  alt=""
                  width={110}
                  height={18}
                  className="h-4 w-auto dark:hidden"
                />
                <Image
                  src="/Sayvors_Wordmark_Dark.png"
                  alt=""
                  width={110}
                  height={18}
                  className="hidden h-4 w-auto dark:block"
                />
              </Link>
              <button
                onClick={() => setDrawerOpen(false)}
                aria-label={t.nav.closeMenu}
                className="ms-auto flex h-8 w-8 items-center justify-center rounded-full text-ink/60 outline-none transition hover:bg-ink/[0.06] hover:text-ink focus-visible:ring-2 focus-visible:ring-deep-violet/40 md:hidden dark:text-fog/60 dark:hover:bg-fog/[0.08] dark:hover:text-fog dark:focus-visible:ring-violet-soft/70"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className="h-4 w-4">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </>
          )}
        </div>

        {/* Nav */}
        <nav
          className={`flex-1 overflow-y-auto pb-2 pt-1 ${rail ? "px-2" : "px-3"}`}
          aria-label={t.nav.mainNavigation}
          onClick={(e) => {
            // Clicking any page link folds Advanced straight away — including a
            // re-click of the current page, where pathname never changes.
            if (!(e.target as HTMLElement).closest("[data-advanced-toggle]")) setAdvancedOpen(false);
          }}
        >
          <div className="space-y-0.5">
            {MAIN_ITEMS.slice(0, 3).map((item) => (
              <NavRow key={item.href} item={item} active={isActive(pathname, item)} rail={rail} label={labelFor(item)} />
            ))}
          </div>
          <ChannelsNav
            pathname={pathname}
            rail={rail}
            labels={t.nav as unknown as Record<string, string>}
            loadingLabel={t.common.loading}
          />
          <div className="mt-0.5 space-y-0.5">
            {MAIN_ITEMS.slice(3).map((item) => (
              <NavRow key={item.href} item={item} active={isActive(pathname, item)} rail={rail} label={labelFor(item)} />
            ))}
          </div>

          {/* Advanced — the long tail, folded away by default. */}
          <div className="mt-2">
            <button
              onClick={toggleAdvanced}
              data-advanced-toggle
              aria-expanded={advancedOpen}
              title={rail ? t.nav.advanced : undefined}
              className={`flex w-full items-center rounded-full py-2 text-ink/60 outline-none transition hover:bg-ink/[0.04] hover:text-ink/80 focus-visible:ring-2 focus-visible:ring-deep-violet/40 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:text-fog/55 dark:hover:bg-fog/[0.05] dark:hover:text-fog/75 dark:focus-visible:ring-violet-soft/70 dark:focus-visible:ring-offset-[#1d1636] ${
                rail ? "justify-center px-0" : "gap-2 px-3"
              }`}
            >
              {!rail && (
                <span className="flex-1 text-start text-[11px] font-medium">
                  {t.nav.advanced}
                </span>
              )}
              <ChevronIcon className={`h-3.5 w-3.5 shrink-0 transition-transform ${advancedOpen ? "rotate-180" : ""}`} />
            </button>
            {advancedOpen && (
              <div className="mt-0.5 space-y-0.5">
                {ADVANCED_ITEMS.map((item) => (
                  <NavRow key={item.href} item={item} active={isActive(pathname, item)} rail={rail} label={labelFor(item)} />
                ))}
              </div>
            )}
          </div>
        </nav>

        {/* Plan / usage. The plan name opens usage; the white circle — and
            the Free-plan hint — open billing, so upgrade and usage stay
            separate destinations. */}
        <div className={`shrink-0 pb-1 ${rail ? "px-2" : "px-3"}`}>
          <UsageCard rail={rail} />
        </div>

        {/* Collapse — the profile itself lives in the header now. */}
        <div className={`hidden shrink-0 pb-2 md:block ${rail ? "px-2" : "px-3"}`}>
          <button
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? t.nav.expand : t.nav.collapse}
            title={collapsed ? t.nav.expand : t.nav.collapse}
            className={`flex h-9 w-full items-center rounded-full text-ink/60 outline-none transition hover:bg-ink/[0.05] hover:text-ink/80 focus-visible:ring-2 focus-visible:ring-deep-violet/40 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:text-fog/55 dark:hover:bg-fog/[0.06] dark:hover:text-fog/75 dark:focus-visible:ring-violet-soft/70 dark:focus-visible:ring-offset-[#1d1636] ${
              rail ? "justify-center" : "gap-2 px-3"
            }`}
          >
            <ChevronIcon
              className={`h-3.5 w-3.5 shrink-0 transition-transform rtl:-scale-x-100 ${rail ? "-rotate-90" : "rotate-90"}`}
            />
            {!rail && <span className="text-[11px] font-medium">{t.nav.collapse}</span>}
          </button>
        </div>
      </aside>
    </>
  );
}

function NavRow({
  item,
  active,
  rail,
  label,
}: {
  item: NavItem;
  active: boolean;
  rail: boolean;
  label: string;
}) {
  return (
    <Link
      href={item.href}
      data-tour={`nav-${item.key}`}
      aria-current={active ? "page" : undefined}
      title={rail ? label : undefined}
      className={`group relative flex h-9 items-center rounded-full text-[13px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-violet-soft/70 dark:focus-visible:ring-offset-[#1d1636] ${
        rail ? "justify-center px-0" : "gap-2.5 px-3"
      } ${
        active
          ? "bg-violet-soft font-semibold text-ink shadow-sm shadow-deep-violet/10 dark:shadow-black/20"
          : "text-ink/65 hover:bg-ink/[0.05] hover:text-ink dark:text-fog/65 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
      }`}
    >
      <span
        aria-hidden
        className={`shrink-0 transition-colors ${
          active ? "text-ink" : "text-ink/50 group-hover:text-ink/80 dark:text-fog/45 dark:group-hover:text-fog/80"
        }`}
      >
        {item.icon}
      </span>
      {!rail && <span className="flex-1 truncate">{label}</span>}
    </Link>
  );
}

// Official provider marks live in /public/channels. Rails/labels unchanged —
// only the glyphs are real logos now instead of emoji.
const CHANNEL_LOGOS: Record<string, string> = {
  whatsapp: "/channels/whatsapp.png",
  instagram: "/channels/instagram.png",
  facebook: "/channels/facebook.png",
};

function ChannelLogo({ channel }: { channel: string }) {
  const src = CHANNEL_LOGOS[channel];
  if (!src) {
    return (
      <span className="flex h-4 w-4 shrink-0 items-center justify-center text-ink/40 dark:text-fog/40">
        <UserIcon />
      </span>
    );
  }
  return (
    <Image
      src={src}
      alt=""
      width={16}
      height={16}
      className="h-4 w-4 shrink-0 object-contain"
    />
  );
}

function ChannelsNav({
  pathname,
  rail,
  labels,
  loadingLabel,
}: {
  pathname: string;
  rail: boolean;
  labels: Record<string, string>;
  loadingLabel: string;
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
        className={`group flex h-9 items-center rounded-full outline-none transition focus-within:ring-2 focus-within:ring-deep-violet/40 focus-within:ring-offset-2 focus-within:ring-offset-white dark:focus-within:ring-violet-soft/70 dark:focus-within:ring-offset-[#1d1636] ${
          activeParent
            ? "bg-violet-soft font-semibold text-ink shadow-sm shadow-deep-violet/10 dark:shadow-black/20"
            : "text-ink/65 hover:bg-ink/[0.05] hover:text-ink dark:text-fog/65 dark:hover:bg-fog/[0.06] dark:hover:text-fog"
        }`}
      >
        <Link
          href="/dashboard/channels/inbox"
          data-tour="nav-channels"
          title={rail ? labels.channels : undefined}
          className={`flex min-w-0 flex-1 items-center outline-none ${rail ? "justify-center" : "gap-2.5 ps-3"}`}
        >
          <span
            aria-hidden
            className={`shrink-0 transition-colors ${
              activeParent ? "text-ink" : "text-ink/50 group-hover:text-ink/80 dark:text-fog/45 dark:group-hover:text-fog/80"
            }`}
          >
            <ChannelsIcon />
          </span>
          {!rail && <span className="flex-1 truncate text-[13px] font-medium">{labels.channels ?? "Channels"}</span>}
        </Link>
        {!rail && (
          <button
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label="Toggle channels"
            className={`me-1.5 flex h-6 w-6 items-center justify-center rounded-full outline-none transition focus-visible:ring-2 focus-visible:ring-ink/30 ${
              activeParent ? "hover:bg-ink/10" : "hover:bg-ink/[0.06] dark:hover:bg-fog/10"
            }`}
          >
            <ChevronIcon className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
        )}
      </div>
      {open && !rail && (
        <div className="ms-5 mt-1 space-y-0.5 border-s border-ink/[0.08] ps-2 dark:border-fog/[0.08]">
          {/* Publish lives on /dashboard/posts-media (one hub: compose,
              published posts, Google library) — it is a top-level page, not
              a channel, so it is not repeated under Channels. */}
          {(!rows || rows.length === 0) && <p className="px-2.5 py-1.5 text-[11px] text-ink/55 dark:text-fog/50">{loadingLabel}</p>}
          {rows?.map((r) =>
            r.key === "overview" ? (
              <Link
                key="overview"
                href="/dashboard/channels"
                className="flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-semibold text-deep-violet outline-none transition hover:bg-ink/[0.05] focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-violet-soft dark:hover:bg-fog/[0.06] dark:focus-visible:ring-violet-soft/60"
              >
                <PlusIcon className="h-3.5 w-3.5" />
                {labelFor("overview")}
              </Link>
            ) : r.key === "connect" ? (
              <Link
                key="connect"
                href="/dashboard/channels"
                data-tour="nav-channels-connect"
                className="flex h-8 items-center gap-1.5 rounded-full px-2.5 text-[12px] font-semibold text-deep-violet outline-none transition hover:bg-ink/[0.05] focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:text-violet-soft dark:hover:bg-fog/[0.06] dark:focus-visible:ring-violet-soft/60"
              >
                <PlusIcon className="h-3.5 w-3.5" />
                {labelFor("connect")}
              </Link>
            ) : (
              <Link
                key={r.key}
                href={hrefFor(r.key)}
                data-tour={`nav-channels-${r.key}`}
                aria-current={pathname === hrefFor(r.key) ? "page" : undefined}
                className={`flex h-8 items-center gap-2 rounded-full px-2.5 text-[12px] font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:focus-visible:ring-violet-soft/60 ${
                  pathname === hrefFor(r.key)
                    ? "bg-ink/[0.06] font-semibold text-deep-violet dark:bg-fog/[0.08] dark:text-violet-soft"
                    : "text-ink/60 hover:bg-ink/[0.05] hover:text-ink/90 dark:text-fog/60 dark:hover:bg-fog/[0.05] dark:hover:text-fog/90"
                }`}
              >
                {r.key === "inbox" ? <InboxIcon /> : <ChannelLogo channel={r.key} />}
                <span className="flex-1 truncate">{labelFor(r.key)}</span>
                {r.key !== "inbox" && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" title="connected" />}
              </Link>
            )
          )}
          {rows && rows.some((r) => r.key !== "connect" && r.key !== "inbox" && r.key !== "overview") && (
            <p className="px-2.5 pt-1.5 text-[10px] font-medium text-ink/55 dark:text-fog/50">{labels.manage ?? "Manage"}</p>
          )}
        </div>
      )}
    </div>
  );
}

function UsageCard({ rail }: { rail: boolean }) {
  const { t } = useI18n();
  const [budget, setBudget] = useState<Budget | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getBudget()
      .then((b) => {
        if (!cancelled) setBudget(b);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const pro = budget?.plan === "pro";
  const planLabel = pro ? t.sidebar.managePlan : t.sidebar.upgradePlan;

  if (rail) {
    return (
      <Link
        href="/dashboard/billing"
        title={planLabel}
        aria-label={planLabel}
        className="flex h-10 w-full items-center justify-center rounded-[14px] bg-violet-soft text-ink outline-none transition hover:bg-violet-soft/90 focus-visible:ring-2 focus-visible:ring-violet-soft/70 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-[#1d1636]"
      >
        <ArrowUpRightIcon />
      </Link>
    );
  }

  if (failed) {
    return (
      <Link
        href="/dashboard/usage"
        className="flex items-center justify-between rounded-[16px] bg-violet-soft px-3 py-3 text-ink outline-none transition hover:bg-violet-soft/90 focus-visible:ring-2 focus-visible:ring-violet-soft/70"
      >
        <span className="text-[12px] font-semibold">{t.sidebar.viewUsage}</span>
        <ArrowUpRightIcon className="h-3.5 w-3.5" />
      </Link>
    );
  }

  return (
    <div className="relative overflow-hidden rounded-[16px] bg-violet-soft p-3 text-ink">
      <div className="flex items-start justify-between gap-2">
        <p className="pt-0.5 text-[10px] font-semibold text-ink/50">{t.sidebar.plan}</p>
        <Link
          href="/dashboard/billing"
          aria-label={planLabel}
          title={planLabel}
          className="-me-1 -mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-ink shadow-sm outline-none transition hover:bg-fog focus-visible:ring-2 focus-visible:ring-ink/30"
        >
          <ArrowUpRightIcon className="h-3.5 w-3.5" />
        </Link>
      </div>
      {budget ? (
        <div className="mt-0.5">
          {/* The plan name opens usage; the line under it is the upgrade
              destination on Free, and stays on usage once the user is Pro. */}
          <Link
            href="/dashboard/usage"
            aria-label={t.sidebar.viewUsage}
            className="block truncate rounded-[6px] text-[15px] font-bold leading-tight outline-none focus-visible:ring-2 focus-visible:ring-ink/30"
          >
            {pro ? t.sidebar.proPlan : t.sidebar.freePlan}
          </Link>
          <Link
            href={pro ? "/dashboard/usage" : "/dashboard/billing"}
            className="mt-0.5 block truncate rounded-[4px] text-[10.5px] font-medium tabular-nums text-ink/55 outline-none transition hover:text-ink/80 focus-visible:ring-2 focus-visible:ring-ink/30"
          >
            {pro ? `$${budget.balance_dollars.toFixed(2)} ${t.sidebar.creditLeft}` : t.sidebar.freeHint}
          </Link>
        </div>
      ) : (
        <span className="mt-1 block h-7 w-3/4 animate-pulse rounded bg-ink/10" />
      )}
      {/* The reference's corner strokes, kept as a quiet texture. */}
      <span aria-hidden className="pointer-events-none absolute bottom-2 end-3 flex flex-col items-end gap-[3px] opacity-20">
        <span className="block h-[2px] w-4 rounded-full bg-ink" />
        <span className="block h-[2px] w-3 rounded-full bg-ink" />
        <span className="block h-[2px] w-2 rounded-full bg-ink" />
      </span>
    </div>
  );
}

/* ── Icons ─────────────────────────────────────── */

function DashboardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function AnalyticsIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </svg>
  );
}

function PinIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0116 0Z" />
      <circle cx="12" cy="10" r="2.5" />
    </svg>
  );
}

function PhotoIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="8.5" cy="9.5" r="1.5" />
      <path d="M21 15l-5-5L5 20" />
    </svg>
  );
}

function UsersIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M17 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2" />
      <circle cx="9.5" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" />
    </svg>
  );
}

function StarIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4 6.1 20.5l1.2-6.5L2.5 9.4l6.6-.9L12 2.5Z" />
    </svg>
  );
}

function DatabaseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <ellipse cx="12" cy="5.5" rx="8" ry="3" />
      <path d="M4 5.5v13c0 1.66 3.58 3 8 3s8-1.34 8-3v-13" />
      <path d="M4 12c0 1.66 3.58 3 8 3s8-1.34 8-3" />
    </svg>
  );
}

function CatalogIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9Z" />
      <path d="M4 7.5 12 12l8-4.5M12 12v9" />
    </svg>
  );
}

function ChannelsIcon() {  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M9 2v6M15 2v6" />
      <path d="M6 8h12v2a6 6 0 01-12 0V8Z" />
      <path d="M12 16v6" />
    </svg>
  );
}

function InboxIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.5 5h13l3.5 7v6a2 2 0 01-2 2H4a2 2 0 01-2-2v-6L5.5 5Z" />
    </svg>
  );
}

function ChevronIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}

function PlusIcon({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" className={className} aria-hidden>
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}

function ArrowUpRightIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d="M5 11L11 5M6 5h5v5" />
    </svg>
  );
}

function ChecklistIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="M3.5 6l1.2 1.2L7 4.9" />
      <path d="M3.5 12l1.2 1.2L7 10.9" />
      <path d="M3.5 18l1.2 1.2L7 16.9" />
    </svg>
  );
}

function ShieldCheckIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
      <path d="M9 12l2 2 4-4" />
    </svg>
  );
}

function OutboxIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M21 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6" />
      <path d="M12 3v12" />
      <path d="M8 7l4-4 4 4" />
    </svg>
  );
}

function CardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20" />
    </svg>
  );
}





function GaugeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-[18px] w-[18px]">
      <path d="M12 15l3.5-3.5" />
      <path d="M20.3 18a9.5 9.5 0 10-16.6 0" />
      <circle cx="12" cy="15" r="1" />
    </svg>
  );
}

function UserIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}


