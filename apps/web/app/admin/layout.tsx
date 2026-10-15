"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { adminClearSession, adminFetch, adminHasSession, adminLogout } from "@/lib/admin-api";

/**
 * Sections, in the order an operator actually works them: is it broken, then
 * who is affected, then why. Order is information, so it is not alphabetical.
 */
const SECTIONS = [
  { href: "/admin/overview", label: "Overview" },
  { href: "/admin/review-issues", label: "Review Issues" },
  { href: "/admin/tenants", label: "Tenants" },
  { href: "/admin/models", label: "AI Models" },
  { href: "/admin/voice-engines", label: "Voice Engines" },
  { href: "/admin/catalogs", label: "Catalogs" },
  { href: "/admin/health", label: "Health" },
];

function isActive(pathname: string, href: string): boolean {
  // Exact for the section itself; prefix for anything nested beneath it.
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [hasSession, setHasSession] = useState(false);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    setHasSession(adminHasSession());
    setReady(true);
  }, []);

  // Re-check on every navigation (login page sets the session), and close the
  // mobile drawer behind the page that was just chosen.
  useEffect(() => {
    setHasSession(adminHasSession());
    setNavOpen(false);
  }, [pathname]);

  const [sessionVerified, setSessionVerified] = useState<boolean | null>(null);
  useEffect(() => {
    if (!ready || !hasSession || pathname === "/admin") {
      if (!hasSession) setSessionVerified(null);
      return;
    }
    let cancelled = false;
    adminFetch<{ admin?: boolean }>("/api/v1/admin/me")
      .then((res) => {
        if (!cancelled) setSessionVerified(res?.admin !== false);
      })
      .catch(() => {
        if (!cancelled) {
          adminClearSession();
          setHasSession(false);
          setSessionVerified(false);
          router.replace("/admin");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [ready, hasSession, pathname]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-fog text-admin-base text-ink/40">
        Loading…
      </div>
    );
  }

  if (!hasSession) {
    // The login form lives at /admin; every other admin page redirects there.
    if (pathname === "/admin") return <>{children}</>;
    router.replace("/admin");
    return (
      <div className="flex min-h-screen items-center justify-center bg-fog text-admin-base text-ink/40">
        Redirecting to login…
      </div>
    );
  }

  const nav = (
    <nav aria-label="Admin sections" className="flex flex-col gap-[var(--ad-3xs)]">
      {SECTIONS.map((s) => {
        const active = isActive(pathname, s.href);
        return (
          <Link
            key={s.href}
            href={s.href}
            aria-current={active ? "page" : undefined}
            className={`relative flex items-center rounded-admin-ctl px-[var(--ad-xs)] py-[var(--ad-2xs)] text-admin-base font-semibold transition-colors ${
              active
                ? "bg-deep-violet/[0.08] text-deep-violet"
                : "text-ink/60 hover:bg-ink/[0.04] hover:text-ink"
            }`}
          >
            {/* The active marker is a rail, not a fill: it survives a colour
                change and does not shift the label. */}
            <span
              aria-hidden
              className={`absolute left-0 top-1/2 h-4 w-[3px] -translate-y-1/2 rounded-full bg-deep-violet transition-opacity ${
                active ? "opacity-100" : "opacity-0"
              }`}
            />
            {s.label}
          </Link>
        );
      })}
    </nav>
  );

  return (
    <div className="admin-ui min-h-screen bg-fog">
      <a
        href="#admin-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-[var(--ad-s)] focus:top-[var(--ad-s)] focus:z-50 focus:rounded-admin-ctl focus:bg-card focus:px-[var(--ad-s)] focus:py-[var(--ad-2xs)] focus:text-admin-base focus:font-bold"
      >
        Skip to content
      </a>

      {/* Sidebar — fixed on desktop, a drawer on narrow screens. Same DOM in
          both, so there is no second nav to keep in sync. */}
      <div className="lg:flex">
        <aside
          aria-label="Admin"
          className={`fixed inset-y-0 left-0 z-40 w-60 border-r border-card-border bg-card px-[var(--ad-s)] py-[var(--ad-m)] transition-transform duration-200 lg:static lg:translate-x-0 ${
            navOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="mb-[var(--ad-l)] flex items-center justify-between">
            <span className="text-admin-md font-bold tracking-tight text-ink">
              Sayvors <span className="text-deep-violet">Admin</span>
            </span>
            <button
              type="button"
              onClick={() => setNavOpen(false)}
              aria-label="Close navigation"
              className="admin-btn border border-ink/10 px-[var(--ad-2xs)] py-1 text-admin-base text-ink/60 lg:hidden"
            >
              Close
            </button>
          </div>

          {nav}

          {hasSession && (
            <div className="mb-[var(--ad-m)] rounded-admin-ctl border border-ink/[0.06] bg-card p-[var(--ad-xs)]">
              <p className="text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/45">
                Operator session
              </p>
              <p className="mt-[var(--ad-3xs)] text-admin-base font-semibold text-ink">
                {sessionVerified === true ? "verified via /admin/me" : sessionVerified === false ? "unverified" : "checking…"}
              </p>
            </div>
          )}

          <button
            type="button"
            onClick={async () => {
              await adminLogout();
              setHasSession(false);
              router.replace("/admin");
            }}
            className="admin-btn mt-[var(--ad-l)] w-full border border-ink/10 text-ink/60 hover:border-coral/40 hover:text-coral"
          >
            Log out
          </button>
        </aside>

        {navOpen && (
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setNavOpen(false)}
            className="fixed inset-0 z-30 bg-ink/30 lg:hidden"
          />
        )}

        <div className="min-w-0 flex-1">
          {/* The mobile bar exists only under lg; the desktop sidebar is always
              present, so this is not a duplicate of the nav. */}
          <div className="sticky top-0 z-20 flex items-center justify-between gap-[var(--ad-s)] border-b border-card-border bg-card px-[var(--ad-s)] py-[var(--ad-xs)] lg:hidden">
            <span className="text-admin-base font-bold text-ink">
              Sayvors <span className="text-deep-violet">Admin</span>
            </span>
            <button
              type="button"
              onClick={() => setNavOpen(true)}
              aria-expanded={navOpen}
              className="admin-btn border border-ink/10 px-[var(--ad-2xs)] py-1 text-admin-base text-ink/70"
            >
              Menu
            </button>
          </div>

          <main
            id="admin-main"
            className="mx-auto w-full max-w-6xl px-[var(--ad-s)] py-[var(--ad-m)] lg:px-[var(--ad-l)]"
          >
            {children}
          </main>
        </div>
      </div>
    </div>
  );
}