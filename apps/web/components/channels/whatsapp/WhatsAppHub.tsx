"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { fetchMetaAssets, type MetaAsset } from "@/lib/api-meta";
import ProfileForm from "./ProfileForm";
import NumbersHealth from "./NumbersHealth";
import WhatsAppSettings from "./WhatsAppSettings";

type Tab = "profile" | "numbers" | "settings";

/* Official WhatsApp palette + doodle. Font matches WhatsApp Web (Segoe UI stack). */
const WA_CSS = `
.wa-font{font-family:"Segoe UI",Helvetica Neue,Helvetica,"Lucida Grande",Arial,sans-serif}
.wa-doodle{background-color:#efeae2;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'%3E%3Cg fill='none' stroke='%23000' stroke-opacity='0.055' stroke-width='1.4'%3E%3Ccircle cx='18' cy='22' r='6'/%3E%3Cpath d='M45 12h14M52 5v14'/%3E%3Crect x='78' y='10' width='12' height='12' rx='2'/%3E%3Cpath d='M10 58q6-8 12 0t12 0'/%3E%3Ccircle cx='52' cy='62' r='3'/%3E%3Cpath d='M78 56l4 8 8 4-8 4-4 8-4-8-8-4 8-4z'/%3E%3Crect x='100' y='52' width='10' height='14' rx='5'/%3E%3Cpath d='M14 92l10-10M24 92L14 82'/%3E%3Ccircle cx='60' cy='100' r='7'/%3E%3Cpath d='M92 92h12M98 86v12'/%3E%3C/g%3E%3C/svg%3E")}
.wa-scroll::-webkit-scrollbar{width:6px}
.wa-scroll::-webkit-scrollbar-thumb{background:rgba(0,0,0,.25)}
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
    <div className="wa-font flex h-full overflow-hidden bg-[#eae6df]">
      <style>{WA_CSS}</style>

      {/* ── Left: WhatsApp chat-list style number picker (tablet/desktop only) ── */}
      <aside className="hidden w-[300px] shrink-0 flex-col border-r border-black/10 bg-white md:flex xl:w-[340px]">
        <div className="flex items-center gap-3 bg-[#008069] px-4 py-3.5 text-white">
          <div className="flex h-10 w-10 items-center justify-center rounded-full bg-white/20 text-lg">💬</div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[16px] font-semibold leading-tight">WhatsApp Business</p>
            <p className="text-[12px] text-white/80">
              {loading ? "loading…" : numbers.length === 0 ? "not connected" : needsFix > 0 ? `${needsFix} need attention` : "all connected"}
            </p>
          </div>
        </div>
        <div className="bg-[#f0f2f5] px-3 py-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search numbers"
            aria-label="Search numbers"
            className="min-h-9 w-full rounded-lg bg-white px-4 text-[13px] text-[#111b21] outline-none placeholder:text-[#667781] focus:ring-2 focus:ring-[#00a884]/40"
          />
        </div>
        <div className="wa-scroll min-h-0 flex-1 overflow-y-auto">
          {loading && (
            <div className="space-y-1 p-2">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex animate-pulse items-center gap-3 px-2 py-2.5">
                  <div className="h-[49px] w-[49px] rounded-full bg-black/10" />
                  <div className="flex-1"><div className="h-3.5 w-2/3 rounded bg-black/10" /><div className="mt-1.5 h-3 w-1/2 rounded bg-black/[0.07]" /></div>
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
                className={`flex w-full items-center gap-3 px-3 py-2.5 text-left transition ${isActive ? "bg-[#f0f2f5]" : "hover:bg-[#f5f6f6]"}`}
              >
                <span className="flex h-[49px] w-[49px] shrink-0 items-center justify-center rounded-full bg-[#00a884]/15 text-[15px] font-semibold text-[#008069]">
                  {initialsOf(n)}
                </span>
                <span className="min-w-0 flex-1 border-b border-black/[0.06] pb-2.5">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-[16px] text-[#111b21]">{n.phone || n.name || "Number"}</span>
                    {!n.active && <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded-full bg-[#00a884] px-1.5 text-[11px] font-bold text-white">!</span>}
                  </span>
                  <span className="mt-0.5 flex items-center justify-between gap-2">
                    <span className="truncate text-[13px] text-[#667781]">{n.name || n.status || "tap to manage"}</span>
                    <span className={`shrink-0 text-[11px] ${n.active ? "text-[#667781]" : "font-semibold text-[#00a884]"}`}>{n.active ? "live" : "fix"}</span>
                  </span>
                </span>
              </button>
            );
          })}
          {!loading && numbers.length === 0 && (
            <div className="p-6 text-center">
              <p className="text-[14px] font-semibold text-[#111b21]">No numbers yet</p>
              <p className="mt-1 text-[13px] text-[#667781]">Connect via Embedded Signup first.</p>
              <Link href="/dashboard/channels" className="mt-3 inline-block rounded-full bg-[#00a884] px-5 py-2 text-[13px] font-semibold text-white">Connect →</Link>
            </div>
          )}
        </div>
        <div className="border-t border-black/[0.06] px-4 py-2.5 text-[12px] text-[#667781]">
          {numbers.length > 0 ? `${numbers.length} number${numbers.length > 1 ? "s" : ""}` : "WhatsApp Cloud API"}
        </div>
      </aside>

      {/* ── Main: doodle chat area ── */}
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 bg-[#f0f2f5] px-4 py-2.5">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#00a884]/15 text-[14px] font-semibold text-[#008069]">
            {active ? initialsOf(active) : "WA"}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold text-[#111b21]">
              {active?.phone || active?.name || "WhatsApp"}
            </p>
            <p className="truncate text-[12px] text-[#667781]">
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
              className="min-h-9 max-w-[140px] shrink-0 truncate rounded-lg bg-white px-2 text-[12px] font-semibold text-[#008069] outline-none focus:ring-2 focus:ring-[#00a884]/40 md:hidden"
            >
              {numbers.map((n) => (
                <option key={n.external_asset_id} value={n.external_asset_id}>
                  {(n.phone || n.name || n.external_asset_id).slice(0, 24)}
                </option>
              ))}
            </select>
          )}
        </header>
        <nav className="flex gap-1 overflow-x-auto bg-white px-4 shadow-[0_1px_2px_rgba(0,0,0,0.08)]" role="tablist" aria-label="WhatsApp sections">
          {(["profile", "numbers", "settings"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => goto(t)}
              className={`min-h-11 shrink-0 border-b-[3px] px-3.5 text-[13px] font-semibold uppercase tracking-wide transition ${tab === t ? "border-[#00a884] text-[#008069]" : "border-transparent text-[#667781] hover:text-[#111b21]"}`}
            >
              {t === "profile" ? "Profile" : t === "numbers" ? "Numbers" : "Settings"}
            </button>
          ))}
        </nav>

        <div className="wa-doodle wa-scroll min-h-0 flex-1 overflow-y-auto p-4 sm:p-6">
          <div className="mx-auto max-w-4xl">
            {loadError && (
              <div role="alert" className="mx-auto mb-3 flex max-w-md items-center gap-2 rounded-lg bg-[#fff3cd] px-4 py-2.5 text-[13px] text-[#664d03] shadow">
                <span className="flex-1">{loadError}</span>
                <button onClick={() => window.location.reload()} className="font-bold underline">Retry</button>
              </div>
            )}
            {numbers.length === 0 && !loading && (
              <div className="mx-auto max-w-md rounded-lg bg-white p-8 text-center shadow-[0_1px_2px_rgba(0,0,0,0.15)]">
                <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-[#00a884]/10 text-3xl">💬</div>
                <p className="mt-3 text-[16px] font-semibold text-[#111b21]">Connect WhatsApp first</p>
                <p className="mt-1 text-[13px] text-[#667781]">Link a number via Embedded Signup, then edit its business profile here.</p>
                <Link href="/dashboard/channels" className="mt-4 inline-block rounded-full bg-[#00a884] px-6 py-2.5 text-[13px] font-semibold text-white">Go to Channels →</Link>
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
