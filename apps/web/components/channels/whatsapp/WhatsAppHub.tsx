"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { fetchMetaAssets, type MetaAsset } from "@/lib/api-meta";
import ProfileForm from "./ProfileForm";
import NumbersHealth from "./NumbersHealth";
import TemplatesList from "./TemplatesList";

const TABS = ["profile", "numbers", "templates", "settings"] as const;
type Tab = (typeof TABS)[number];

const TOKENS = ":root{--wa-paper:#F6F3EC;--wa-ink:#16130E;--wa-green:#25D366}";

export default function WhatsAppHub() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as Tab) || "profile";
  const locParam = params.get("location") ?? "";
  const [numbers, setNumbers] = useState<MetaAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let dead = false;
    (async () => {
      try {
        const r = await fetchMetaAssets("whatsapp");
        if (!dead) setNumbers((r.assets ?? []).filter((a) => a.asset_type === "phone_number"));
      } catch (e) {
        if (!dead) setLoadError(e instanceof Error ? e.message : "Could not load numbers.");
      } finally {
        if (!dead) setLoading(false);
      }
    })();
    return () => {
      dead = true;
    };
  }, []);

  const activeId = useMemo(
    () => locParam || numbers.find((n) => n.active)?.external_asset_id || numbers[0]?.external_asset_id || "",
    [locParam, numbers]
  );
  const active = numbers.find((n) => n.external_asset_id === activeId) ?? numbers[0] ?? null;

  const goto = (t: Tab, loc?: string) => {
    const q = new URLSearchParams();
    q.set("tab", t);
    if (loc ?? activeId) q.set("location", (loc ?? activeId) as string);
    router.replace(`?${q.toString()}`);
  };

  return (
    <div className="flex h-full flex-col" style={{ background: "#F6F3EC" }}>
      <style>{TOKENS}</style>
      <div className="border-b border-black/[0.06] bg-white px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-[#25D366] text-xl text-white shadow-md">💬</div>
          <div className="min-w-0 flex-1">
            <h1 className="text-[18px] font-bold text-[#16130E]">WhatsApp</h1>
            <p className="text-[12px] text-black/50">
              {loading ? "Loading numbers…" : numbers.length === 0 ? "Not connected yet" : `${numbers.length} number${numbers.length > 1 ? "s" : ""} · ${active?.phone ?? active?.name ?? ""}`}
            </p>
          </div>
          {numbers.length > 1 && (
            <select
              value={activeId}
              onChange={(e) => goto(tab as Tab, e.target.value)}
              aria-label="Switch location / number"
              className="min-h-11 rounded-xl border border-black/10 bg-white px-3 text-[13px] font-semibold outline-none focus:border-[#25D366]"
            >
              {numbers.map((n) => (
                <option key={n.external_asset_id} value={n.external_asset_id}>
                  {(n.name || n.phone || n.external_asset_id).slice(0, 32)}
                </option>
              ))}
            </select>
          )}
          <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${active?.active ? "bg-emerald-500/15 text-emerald-700" : "bg-black/[0.05] text-black/50"}`}>
            {active?.active ? "● Connected" : active ? "○ Check needed" : "○ Off"}
          </span>
        </div>
        <div className="mt-3 flex gap-1 overflow-x-auto" role="tablist" aria-label="WhatsApp sections">
          {(["profile", "numbers", "templates", "settings"] as Tab[]).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => goto(t)}
              className={`min-h-11 shrink-0 rounded-xl px-3.5 text-[13px] font-semibold transition ${tab === t ? "bg-[#16130E] text-white" : "text-black/55 hover:bg-black/[0.04]"}`}
            >
              {t === "profile" ? "Profile" : t === "numbers" ? "Numbers & Health" : t === "templates" ? "Templates" : "Settings"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className="mx-auto max-w-5xl">
          {loadError && (
            <p role="alert" className="mb-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-[13px] text-red-700">
              {loadError} <button onClick={() => window.location.reload()} className="font-bold underline">Retry</button>
            </p>
          )}
          {numbers.length === 0 && !loading && (
            <div className="rounded-2xl bg-white p-6 text-center shadow-sm">
              <p className="text-[15px] font-bold">Connect WhatsApp first</p>
              <p className="mt-1 text-[13px] text-black/50">Link a number via Embedded Signup, then edit its business profile here.</p>
              <Link href="/dashboard/channels" className="mt-4 inline-block min-h-11 rounded-xl bg-[#25D366] px-5 py-2.5 text-[13px] font-bold text-white">Go to Channels →</Link>
            </div>
          )}
          {active && tab === "profile" && <ProfileForm phoneId={active.external_asset_id} />}
          {active && tab === "numbers" && <NumbersHealth numbers={numbers} activeId={active.external_asset_id} />}
          {active && tab === "templates" && <TemplatesList />}
          {tab === "settings" && (
            <div className="rounded-2xl bg-white p-5 shadow-sm">
              <p className="text-[14px] font-bold">Settings</p>
              <p className="mt-1 text-[13px] text-black/50">Agent, response style, auto-reply and working hours live in the channel settings page.</p>
              <Link href="/dashboard/channels/whatsapp/settings" className="mt-3 inline-block min-h-11 rounded-xl border border-black/10 px-4 py-2.5 text-[13px] font-semibold">Open channel settings →</Link>
            </div>
          )}
        </div>
      </div>
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
