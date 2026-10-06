"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { fetchMetaAssets, type MetaAsset } from "@/lib/api-meta";
import ProfileForm from "./ProfileForm";
import NumbersHealth from "./NumbersHealth";
import WhatsAppSettings from "./WhatsAppSettings";

type Tab = "profile" | "numbers" | "settings";

/* Official WhatsApp palette — light AND dark. The hub follows the app's .dark
 * class (ThemeProvider toggles it on <html>): light keeps the classic WhatsApp
 * Web look; dark uses WhatsApp's real dark-theme colors so the hub never sits
 * as a bright white panel inside the dark app shell. Components read these
 * tokens via Tailwind arbitrary values, e.g. bg-[var(--wa-panel)]. */
const WA_CSS = `
.wa-skin{
  --wa-bg:#eae6df; --wa-panel:#ffffff; --wa-panel-2:#f0f2f5; --wa-hover:#f5f6f6;
  --wa-text:#111b21; --wa-text-2:#667781; --wa-text-3:#8696a0; --wa-label:#3b4a54;
  --wa-border:rgba(11,20,26,0.10); --wa-border-soft:rgba(11,20,26,0.06);
  --wa-header-bg:#008069; --wa-header-text:#ffffff; --wa-header-muted:rgba(255,255,255,0.8);
  --wa-deep:#075e54; --wa-on-deep:#ffffff; --wa-on-deep-muted:rgba(255,255,255,0.8);
  --wa-accent:#00a884; --wa-accent-deep:#008069;
  --wa-input-bg:#ffffff; --wa-input-border:#d1d7db;
  --wa-bubble-in:#ffffff; --wa-bubble-out:#d9fdd3;
  --wa-frame:#0b141a; --wa-track:rgba(11,20,26,0.08);
  --wa-warn-bg:#fff3cd; --wa-warn-text:#664d03;
  --wa-ok-bg:#d1f4cc; --wa-ok-text:#0f5132;
  --wa-danger:#d93025;
}
.dark .wa-skin{
  --wa-bg:#0b141a; --wa-panel:#111b21; --wa-panel-2:#202c33; --wa-hover:#202c33;
  --wa-text:#e9edef; --wa-text-2:#8696a0; --wa-text-3:#8696a0; --wa-label:#d1d7db;
  --wa-border:rgba(233,237,239,0.10); --wa-border-soft:rgba(233,237,239,0.06);
  --wa-header-bg:#202c33; --wa-header-text:#e9edef; --wa-header-muted:#8696a0;
  --wa-deep:#202c33; --wa-on-deep:#e9edef; --wa-on-deep-muted:#8696a0;
  --wa-accent:#00a884; --wa-accent-deep:#00a884;
  --wa-input-bg:#2a3942; --wa-input-border:rgba(233,237,239,0.10);
  --wa-bubble-in:#202c33; --wa-bubble-out:#005c4b;
  --wa-frame:#111b21; --wa-track:rgba(233,237,239,0.12);
  --wa-warn-bg:#3a3116; --wa-warn-text:#ffd970;
  --wa-ok-bg:#113b29; --wa-ok-text:#6ee7a0;
  --wa-danger:#ff7a7a;
}
.wa-font{font-family:"Segoe UI",Helvetica Neue,Helvetica,"Lucida Grande",Arial,sans-serif}
.wa-chat-canvas{background-color:#efeae2;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='none' stroke='%23000' stroke-opacity='0.055' stroke-width='1.4'%3E%3Ccircle cx='18' cy='22' r='6'/%3E%3Cpath d='M45 12h14M52 5v14'/%3E%3Crect x='78' y='10' width='12' height='12' rx='2'/%3E%3Cpath d='M10 58q6-8 12 0t12 0'/%3E%3Ccircle cx='52' cy='62' r='3'/%3E%3Cpath d='M78 56l4 8 8 4-8 4-4 8-4-8-8-4 8-4z'/%3E%3Crect x='100' y='52' width='10' height='14' rx='5'/%3E%3Cpath d='M14 92l10-10M24 92L14 82'/%3E%3Ccircle cx='60' cy='100' r='7'/%3E%3Cpath d='M92 92h12M98 86v12'/%3E%3C/g%3E%3C/svg%3E")}
.dark .wa-chat-canvas{background-color:#0b141a;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='none' stroke='%23ffffff' stroke-opacity='0.04' stroke-width='1.4'%3E%3Ccircle cx='18' cy='22' r='6'/%3E%3Cpath d='M45 12h14M52 5v14'/%3E%3Crect x='78' y='10' width='12' height='12' rx='2'/%3E%3Cpath d='M10 58q6-8 12 0t12 0'/%3E%3Ccircle cx='52' cy='62' r='3'/%3E%3Cpath d='M78 56l4 8 8 4-8 4-4 8-4-8-8-4 8-4z'/%3E%3Crect x='100' y='52' width='10' height='14' rx='5'/%3E%3Cpath d='M14 92l10-10M24 92L14 82'/%3E%3Ccircle cx='60' cy='100' r='7'/%3E%3Cpath d='M92 92h12M98 86v12'/%3E%3C/g%3E%3C/svg%3E")}
.wa-scroll::-webkit-scrollbar{width:6px}
.wa-scroll::-webkit-scrollbar-thumb{background:rgba(128,128,128,.35)}
`;

function initialsOf(n: MetaAsset): string {
  const base = (n.name || n.phone || "?").trim();
  const parts = base.split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return base.slice(0, 2).toUpperCase();
}

export default function WhatsAppHub() {
  const params = useSearchParams();
  const router = useRouter();
  const rawTab = params.get("tab");
  const tab: Tab = (["profile", "numbers", "settings"] as string[]).includes(rawTab ?? "") ? (rawTab as Tab) : "profile";
  const locParam = params.get("location") ?? "";
  const [numbers, setNumbers] = useState<MetaAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  // Reloadable so child actions (register a number, re-validate) can refresh
  // the list without a full page reload.
  const loadNumbers = useCallback(async () => {
    try {
      const r = await fetchMetaAssets("whatsapp");
      setNumbers((r.assets ?? []).filter((a) => a.asset_type === "phone_number"));
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Could not load numbers.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const r = await fetchMetaAssets("whatsapp");
        if (dead) return;
        setNumbers((r.assets ?? []).filter((a) => a.asset_type === "phone_number"));
        setLoadError(null);
      } catch (e) {
        if (dead) return;
        setLoadError(e instanceof Error ? e.message : "Could not load numbers.");
      } finally {
        if (!dead) setLoading(false);
      }
    })();
    return () => {
      dead = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return numbers;
    return numbers.filter((n) => `${n.name ?? ""} ${n.phone ?? ""}`.toLowerCase().includes(q));
  }, [numbers, query]);

  const activeId = useMemo(
    () => locParam || numbers.find((n) => n.active)?.external_asset_id || numbers[0]?.external_asset_id || "",
    [locParam, numbers]
  );
  const active = numbers.find((n) => n.external_asset_id === activeId) ?? numbers[0] ?? null;
  const needsFix = numbers.filter((n) => !n.active).length;

  const goto = (t: Tab, loc?: string) => {
    const q = new URLSearchParams();
    q.set("tab", t);
    const l = loc ?? activeId;
    if (l) q.set("location", l);
    router.replace(`?${q.toString()}`);
  };

  return (
    <div className="wa-skin wa-font flex h-full overflow-hidden bg-[var(--wa-bg)] text-[var(--wa-text)]">
      <style>{WA_CSS}</style>

      {/* ── Left: business number manager (tablet/desktop only) ── */}
      <aside className="hidden w-[300px] shrink-0 flex-col border-r border-[var(--wa-border)] bg-[var(--wa-panel)] md:flex xl:w-[340px]">
        <div className="flex items-center gap-3 bg-[var(--wa-header-bg)] px-4 py-3.5 text-[var(--wa-header-text)]">
          <img src="/channels/whatsapp-logo.png" alt="WhatsApp" className="h-9 w-auto object-contain" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[16px] font-semibold leading-tight">Business Numbers</p>
            <p className="text-[12px] text-[var(--wa-header-muted)]">
              {loading ? "loading…" : numbers.length === 0 ? "not connected" : needsFix > 0 ? `${needsFix} need attention` : "all connected"}
            </p>
          </div>
        </div>
        <div className="bg-[var(--wa-panel-2)] px-3 py-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search business numbers…"
            aria-label="Search business numbers"
            className="min-h-9 w-full rounded-lg bg-[var(--wa-input-bg)] px-4 text-[13px] text-[var(--wa-text)] outline-none placeholder:text-[var(--wa-text-2)] focus:ring-2 focus:ring-[var(--wa-accent)]/40"
          />
        </div>
        <div className="wa-scroll min-h-0 flex-1 overflow-y-auto">
          {loading && (
            <div className="space-y-1 p-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex animate-pulse items-center gap-3 px-2 py-2.5">
                  <div className="h-[49px] w-[49px] rounded-xl bg-[var(--wa-track)]" />
                  <div className="flex-1"><div className="h-3.5 w-2/3 rounded bg-[var(--wa-track)]" /><div className="mt-1.5 h-3 w-1/2 rounded bg-[var(--wa-track)]" /></div>
                </div>
              ))}
            </div>
          )}
          {!loading && filtered.map((n) => {
            const isActive = n.external_asset_id === activeId;
            return (
              <button
                key={n.external_asset_id}
                onClick={() => goto(tab, n.external_asset_id)}
                aria-current={isActive}
                className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition ${isActive ? "bg-[var(--wa-panel-2)]" : "hover:bg-[var(--wa-hover)]"}`}
              >
                <span className="flex h-[49px] w-[49px] shrink-0 items-center justify-center rounded-xl bg-[var(--wa-accent)]/15 text-[var(--wa-accent-deep)]">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-6 w-6"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6" strokeLinecap="round" strokeLinejoin="round"/></svg>
                </span>
                <span className="min-w-0 flex-1 border-b border-[var(--wa-border-soft)] pb-2.5">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[16px] text-[var(--wa-text)]">{n.phone || n.name || "Number"}</span>
                    {!n.active && <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-[var(--wa-accent)] px-1.5 text-[11px] font-bold text-white">!</span>}
                  </span>
                  <span className="mt-0.5 flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] text-[var(--wa-text-2)]">{n.name || "WhatsApp Business number"}</span>
                    <span className={`shrink-0 text-[11px] ${n.active ? "text-[var(--wa-text-2)]" : "font-semibold text-[var(--wa-accent)]"}`}>{n.active ? "live" : "fix"}</span>
                  </span>
                </span>
              </button>
            );
          })}
          {!loading && numbers.length === 0 && (
            <div className="p-6 text-center">
              <p className="text-[14px] font-semibold text-[var(--wa-text)]">No business numbers yet</p>
              <p className="mt-1 text-[13px] text-[var(--wa-text-2)]">Connect via Embedded Signup first.</p>
              <Link href="/dashboard/channels" className="mt-3 inline-block rounded-full bg-[var(--wa-accent)] px-5 py-2 text-[13px] font-semibold text-white">Connect →</Link>
            </div>
          )}
        </div>
        <div className="border-t border-[var(--wa-border-soft)] px-4 py-2.5 text-[12px] text-[var(--wa-text-2)]">
          {numbers.length > 0 ? `${numbers.length} business number${numbers.length > 1 ? "s" : ""}` : "WhatsApp Cloud API"}
        </div>
      </aside>

      {/* ── Main: doodle chat area ── */}
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 bg-[var(--wa-panel-2)] px-4 py-2.5">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[var(--wa-accent)]/15 text-[14px] font-semibold text-[var(--wa-accent-deep)]">
            {active ? initialsOf(active) : "WA"}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold text-[var(--wa-text)]">
              {active?.phone || active?.name || "WhatsApp"}
            </p>
            <p className="truncate text-[12px] text-[var(--wa-text-2)]">
              {loading
                ? "loading…"
                : active
                  ? active.active
                    ? `online · ${active.status || "connected"}`
                    : "needs attention"
                  : "not connected"}
            </p>
          </div>
          {/* Mobile number picker — the sidebar list is hidden below md */}
          {numbers.length > 1 && (
            <select
              value={activeId}
              onChange={(e) => goto(tab, e.target.value)}
              aria-label="Switch number"
              className="min-h-9 max-w-[140px] shrink-0 truncate rounded-lg bg-[var(--wa-panel)] px-2 text-[12px] font-semibold text-[var(--wa-accent-deep)] outline-none focus:ring-2 focus:ring-[var(--wa-accent)]/40 md:hidden"
            >
              {numbers.map((n) => (
                <option key={n.external_asset_id} value={n.external_asset_id}>
                  {(n.phone || n.name || n.external_asset_id).slice(0, 24)}
                </option>
              ))}
            </select>
          )}
        </header>
        <nav className="flex gap-1 overflow-x-auto bg-[var(--wa-panel)] px-4 shadow-[0_1px_2px_rgba(0,0,0,0.08)]" role="tablist" aria-label="WhatsApp sections">
          {(["profile", "numbers", "settings"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => goto(t)}
              className={`min-h-11 shrink-0 border-b-[3px] px-3.5 text-[13px] font-semibold uppercase tracking-wide transition ${tab === t ? "border-[var(--wa-accent)] text-[var(--wa-accent-deep)]" : "border-transparent text-[var(--wa-text-2)] hover:text-[var(--wa-text)]"}`}
            >
              {t === "profile" ? "Profile" : t === "numbers" ? "Numbers" : "Settings"}
            </button>
          ))}
        </nav>

        <div className="wa-chat-canvas wa-scroll min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
          <div className="mx-auto max-w-4xl">
            {loadError && (
              <div role="alert" className="mx-auto mb-3 flex max-w-md items-center gap-2 rounded-lg bg-[var(--wa-warn-bg)] px-4 py-2.5 text-[13px] text-[var(--wa-warn-text)] shadow">
                <span className="flex-1">{loadError}</span>
                <button onClick={() => window.location.reload()} className="font-bold underline">Retry</button>
              </div>
            )}
            {numbers.length === 0 && !loading && (
              <div className="mx-auto max-w-md rounded-lg bg-[var(--wa-panel)] p-8 text-center shadow-[0_1px_2px_rgba(0,0,0,0.15)]">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-[var(--wa-accent)]/10 text-3xl">💬</div>
                <p className="mt-3 text-[16px] font-semibold text-[var(--wa-text)]">Connect WhatsApp first</p>
                <p className="mt-1 text-[13px] text-[var(--wa-text-2)]">Link a number via Embedded Signup, then edit its business profile here.</p>
                <Link href="/dashboard/channels" className="mt-4 inline-block rounded-full bg-[var(--wa-accent)] px-6 py-2.5 text-[13px] font-semibold text-white">Go to Channels →</Link>
              </div>
            )}
            {/* key= remounts the form per number, so its loading state resets cleanly */}
            {active && tab === "profile" && <ProfileForm key={active.external_asset_id} phoneId={active.external_asset_id} businessName={active.name} />}
            {active && tab === "numbers" && (
              <NumbersHealth numbers={numbers} activeId={active.external_asset_id} onRefresh={loadNumbers} />
            )}
            {active && tab === "settings" && (
              <WhatsAppSettings
                phoneId={active.external_asset_id}
                phone={active.phone}
                businessName={active.name}
              />
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

export function WhatsAppHubSuspense() {
  return (
    <Suspense>
      <WhatsAppHub />
    </Suspense>
  );
}
