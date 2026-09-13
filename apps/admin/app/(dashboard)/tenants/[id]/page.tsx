"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useMemo, useState } from "react";
import { adminFetch, type AdminTenantDetail } from "@/lib/admin-api";

type Review = AdminTenantDetail["recent_reviews"][number];

interface TenantUsage {
  days: number;
  totals: { calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number; avg_latency_ms: number };
  by_model: { model: string; api_model: string; calls: number; total_tokens: number; avg_latency_ms: number }[];
  by_purpose: { purpose: string; calls: number; total_tokens: number }[];
  daily: { day: string; total_tokens: number; calls: number }[];
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  } catch { return iso; }
}
function fmtDateTime(iso: string | null): string {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }); } catch { return iso; }
}
function fmtRelative(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  if (diff < 2_592_000_000) return `${Math.floor(diff / 86_400_000)}d ago`;
  return fmtDate(iso);
}
function initialsFromTenant(t: AdminTenantDetail): string {
  const a = (t.first_name?.[0] ?? t.email[0] ?? "?").toUpperCase();
  const b = (t.last_name?.[0] ?? t.email[1] ?? "").toUpperCase();
  return (a + (b && b !== a ? b : "")).slice(0, 2);
}
function sentimentStyle(s: string): string {
  const v = s.toLowerCase();
  if (v.includes("pos")) return "bg-emerald-50 text-emerald-700 ring-emerald-200";
  if (v.includes("neg")) return "bg-red-50 text-red-700 ring-red-200";
  if (v.includes("mix") || v.includes("neu")) return "bg-amber-50 text-amber-700 ring-amber-200";
  return "bg-ink/[0.06] text-ink/60 ring-ink/10";
}
function statusStyle(s: string): string {
  const v = s.toLowerCase();
  if (v === "published") return "bg-emerald-500 text-white";
  if (v === "scheduled") return "bg-sky-500 text-white";
  if (v === "draft") return "bg-amber-400 text-white";
  if (v === "failed") return "bg-red-500 text-white";
  if (v === "pending") return "bg-violet-500 text-white";
  return "bg-ink/10 text-ink/60";
}
function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
function fmtMs(ms: number): string { return ms >= 1000 ? `${(ms/1000).toFixed(1)}s` : `${ms}ms`; }
function Stars({ rating }: { rating: number }) {
  const n = Math.max(0, Math.min(5, Math.round(rating)));
  return (
    <span aria-label={`${rating} out of 5 stars`} className="inline-flex">
      {Array.from({ length: 5 }).map((_, i) => (
        <svg key={i} width="11" height="11" viewBox="0 0 24 24" fill={i < n ? "currentColor" : "none"} className={i < n ? "text-amber-500" : "text-ink/15"} aria-hidden>
          <path d="M12 3.6l1.9 3.9 4.3.6-3.1 3 0.7 4.3L12 13.5 8.2 15.4l0.7-4.3-3.1-3 4.3-.6L12 3.6z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        </svg>
      ))}
    </span>
  );
}
function MiniArea({ points }: { points: { x: string; y: number }[] }) {
  const W = 520, H = 86, PAD = 26;
  const max = Math.max(1, ...points.map((p) => p.y));
  const n = Math.max(1, points.length - 1);
  const px = (i: number) => PAD + (i / n) * (W - PAD * 2);
  const py = (v: number) => H - 14 - (v / max) * (H - 28);
  const line = points.map((p, i) => `${i===0?"M":"L"}${px(i).toFixed(1)},${py(p.y).toFixed(1)}`).join(" ");
  const area = `${line} L${px(points.length-1).toFixed(1)},${(H-14).toFixed(1)} L${PAD},${(H-14).toFixed(1)} Z`;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full text-ink">
      <line x1={PAD} x2={W-PAD} y1={py(max)} y2={py(max)} stroke="currentColor" strokeOpacity={0.06} />
      <path d={area} fill="#5b2d8e" opacity={0.1} />
      <path d={line} fill="none" stroke="#5b2d8e" strokeWidth={1.6} strokeLinejoin="round" />
      {points.map((p,i)=><circle key={i} cx={px(i)} cy={py(p.y)} r={1.4} fill="#5b2d8e"><title>{`${p.x}: ${p.y.toLocaleString()}`}</title></circle>)}
      <text x={PAD} y={H-3} fontSize={8.5} fill="currentColor" opacity={0.35}>{points[0]?.x ?? ""}</text>
      <text x={W-PAD} y={H-3} textAnchor="end" fontSize={8.5} fill="currentColor" opacity={0.35}>{points[points.length-1]?.x ?? ""}</text>
    </svg>
  );
}

export default function AdminTenantDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [tenant, setTenant] = useState<AdminTenantDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [selected, setSelected] = useState<Review | null>(null);
  // AI usage
  const [usage, setUsage] = useState<TenantUsage | null>(null);
  const [usageDays, setUsageDays] = useState(30);
  const [usageLoading, setUsageLoading] = useState(true);
  const [usageError, setUsageError] = useState<string|null>(null);

  useEffect(() => {
    let cancelled = false;
    adminFetch<AdminTenantDetail>(`/api/v1/admin/tenants/${encodeURIComponent(id)}`)
      .then((t) => { if (!cancelled) setTenant(t); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : "Load failed."); });
    return () => { cancelled = true; };
  }, [id]);

  const loadUsage = useCallback(async (days: number) => {
    setUsageLoading(true); setUsageError(null);
    try { setUsage(await adminFetch<TenantUsage>(`/api/v1/admin/tenants/${encodeURIComponent(id)}/usage?days=${days}`)); }
    catch (e) {
      const msg = e instanceof Error ? e.message : "Usage load failed";
      // Endpoint returns 404 when API hasn't reloaded — fallback to global overview filtered to this tenant
      const isNotFound = msg.includes("Not Found") || msg.includes("404") || msg.includes("Tenant not found");
      if (isNotFound) {
        try {
          const global = await adminFetch<{ per_tenant: { tenant_id: string | null; email: string; calls: number; total_tokens: number; avg_latency_ms: number; last_seen: string|null }[]; daily: { day: string; total_tokens: number; calls: number }[] }>(`/api/v1/admin/usage/overview?days=${days}`);
          const row = global.per_tenant.find((t) => t.tenant_id === id);
          if (row) {
            setUsage({
              days,
              totals: { calls: row.calls, prompt_tokens: 0, completion_tokens: 0, total_tokens: row.total_tokens, avg_latency_ms: row.avg_latency_ms },
              by_model: [],
              by_purpose: [],
              daily: [],
            });
            // keep a soft hint, not an error — still useful data from global rollup
            setUsageError("Detailed per-tenant history needs API restart — showing summary from global rollup. Restart API to enable full chart.");
            return;
          }
          // tenant has no usage in window — treat as empty, not error
          setUsage({ days, totals: { calls: 0, prompt_tokens: 0, completion_tokens: 0, total_tokens: 0, avg_latency_ms: 0 }, by_model: [], by_purpose: [], daily: [] });
          setUsageError(null);
          return;
        } catch {}
      }
      setUsageError(msg); setUsage(null);
    }
    finally { setUsageLoading(false); }
  }, [id]);

  useEffect(() => { void loadUsage(usageDays); }, [usageDays, loadUsage]);

  // close modal on Escape
  useEffect(() => {
    if (!selected) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setSelected(null); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [selected]);

  const stage = useMemo(() => {
    if (!tenant) return 1;
    if (tenant.has_connection) return 3;
    if (tenant.email_verified) return 2;
    return 1;
  }, [tenant]);

  if (error) {
    return (
      <div className="rounded-2xl border-2 border-white bg-white/80 p-10 text-center">
        <p className="text-[14px] font-bold text-ink">{error}</p>
        <p className="mt-1 text-[12px] text-ink/45">Tenant ID: {id}</p>
        <Link href="/tenants" className="mt-4 inline-flex rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white hover:bg-[#4a2575]">← Back to tenants</Link>
      </div>
    );
  }
  if (!tenant) {
    return (
      <div className="space-y-4" aria-hidden>
        <div className="h-6 w-40 animate-pulse rounded-full bg-white/60" />
        <div className="h-44 animate-pulse rounded-2xl bg-white/60" />
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="h-64 animate-pulse rounded-2xl bg-white/60" />
          <div className="h-64 animate-pulse rounded-2xl bg-white/60" />
        </div>
      </div>
    );
  }

  const name = [tenant.first_name, tenant.last_name].filter(Boolean).join(" ");
  const displayName = name || tenant.email.split("@")[0];
  const maxModelTokens = Math.max(1, ...(usage?.by_model.map((m)=>m.total_tokens) ?? [1]));

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <nav className="flex items-center gap-2 text-[12px]">
          <Link href="/tenants" className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-1.5 text-[12px] font-semibold text-ink/60 ring-1 ring-ink/[0.06] hover:bg-ink/[0.03] hover:text-ink">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M14.5 6l-6 6 6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg> Tenants
          </Link>
          <span className="text-ink/20" aria-hidden>›</span>
          <span className="max-w-[260px] truncate font-semibold text-ink" title={tenant.email}>{tenant.email}</span>
          <span className={`hidden shrink-0 rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-wide sm:inline-flex ${tenant.email_verified ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-1 ring-amber-200"}`}>{tenant.email_verified ? "Verified" : "Unverified"}</span>
        </nav>
        <div className="flex items-center gap-2">
          <span className="hidden truncate rounded-full bg-ink/[0.04] px-2.5 py-1 font-mono text-[11px] text-ink/50 sm:inline-flex" title={tenant.id}>{tenant.id.slice(0, 8)}…{tenant.id.slice(-4)}</span>
          <button onClick={async()=>{ try{ await navigator.clipboard.writeText(tenant.id); setCopied(true); setTimeout(()=>setCopied(false),1400);}catch{}}} className="rounded-xl border border-ink/[0.08] bg-white px-3 py-1.5 text-[11px] font-semibold text-ink/60 hover:bg-ink/[0.03] hover:text-ink">{copied?"Copied!":"Copy ID"}</button>
        </div>
      </div>

      {/* Hero */}
      <div className="overflow-hidden rounded-2xl border-2 border-white bg-white/85 shadow-sm">
        <div className="bg-gradient-to-r from-deep-violet/[0.06] via-violet-500/[0.04] to-sky-500/[0.05] px-5 py-5 sm:px-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex gap-4">
              <div className="relative shrink-0">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-deep-violet text-[16px] font-black tracking-tight text-white shadow-sm ring-1 ring-deep-violet/20">{initialsFromTenant(tenant)}</div>
                <span className={`absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full border-2 border-white text-[10px] font-bold ${tenant.email_verified ? "bg-emerald-500 text-white" : "bg-amber-400 text-white"}`} aria-hidden>{tenant.email_verified ? "✓":"!"}</span>
              </div>
              <div className="min-w-0">
                <h1 className="truncate text-[18px] font-bold leading-none tracking-tight text-ink" title={tenant.email}>{tenant.email}</h1>
                <p className="mt-1.5 flex flex-wrap items-center gap-2 text-[12px] text-ink/60">
                  <span className="font-semibold text-ink/80">{displayName}</span>
                  <span className="rounded-full bg-white px-2 py-1 text-[11px] font-medium text-ink/60 ring-1 ring-ink/[0.06]">Joined {fmtDate(tenant.created_at)} · {fmtRelative(tenant.created_at)}</span>
                </p>
                <p className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                  <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ${tenant.email_verified ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-1 ring-amber-200"}`}><span className={`h-2 w-2 rounded-full ${tenant.email_verified?"bg-emerald-500":"bg-amber-500"}`} aria-hidden/> {tenant.email_verified?"Email verified":"Email unverified"}</span>
                  <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ring-1 ${tenant.has_connection?"bg-emerald-50 text-emerald-700 ring-emerald-200":"bg-ink/[0.04] text-ink/50 ring-ink/10"}`}><span className={`h-2 w-2 rounded-full ${tenant.has_connection?"bg-emerald-500":"bg-ink/30"}`} aria-hidden/> {tenant.has_connection?"Listing connected":"No listing"}</span>
                  <span className="hidden text-ink/20 sm:inline">·</span>
                  <span className="font-mono text-[11px] text-ink/35">{tenant.id}</span>
                </p>
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 self-start">
              <Link href="/tenants" className="rounded-xl bg-white px-3 py-2 text-[12px] font-semibold text-ink/60 ring-1 ring-ink/[0.08] hover:bg-ink/[0.03] hover:text-ink">Back to list</Link>
              <Link href={`/usage`} className="rounded-xl bg-deep-violet px-3 py-2 text-[12px] font-bold text-white shadow-sm hover:bg-[#4a2575]">Usage →</Link>
            </div>
          </div>
          <div className="mt-5 rounded-2xl bg-white/80 p-3 ring-1 ring-ink/[0.06]">
            <div className="flex items-center justify-between gap-2">
              {[
                { n:1, label:"Signed up", desc:fmtDate(tenant.created_at), done:true },
                { n:2, label:"Verified", desc:tenant.email_verified?"Verified":"Awaiting", done:stage>=2 },
                { n:3, label:"Connected", desc:tenant.has_connection? (tenant.listing_name ?? "Connected") : "Not yet", done:stage>=3 },
              ].map((s,i,arr)=>(
                <div key={s.n} className="flex flex-1 items-center gap-2">
                  <div className="flex items-center gap-2">
                    <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ring-1 ${s.done?"bg-deep-violet text-white ring-deep-violet":"bg-white text-ink/30 ring-ink/10"}`}>{s.done?"✓":s.n}</span>
                    <div className="hidden min-w-0 sm:block">
                      <p className={`text-[12px] font-semibold leading-none ${s.done?"text-ink":"text-ink/40"}`}>{s.label}</p>
                      <p className="mt-1 truncate text-[11px] leading-none text-ink/45" title={s.desc}>{s.desc}</p>
                    </div>
                    <div className="sm:hidden"><p className={`text-[11px] font-bold leading-none ${s.done?"text-ink":"text-ink/40"}`}>{s.label}</p></div>
                  </div>
                  {i<arr.length-1 && <div className={`mx-2 h-px flex-1 ${stage> s.n?"bg-deep-violet/30":"bg-ink/[0.08]"}`} aria-hidden/>}
                </div>
              ))}
            </div>
            {stage<3 && <p className="mt-2.5 rounded-xl bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800 ring-1 ring-amber-200">{stage===1?"Next: tenant needs to verify email — no connection can sync until then.":"Next: verified account hasn't connected a listing — activation gap."}</p>}
          </div>
        </div>
        <div className="grid gap-2.5 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-2xl bg-ink/[0.02] p-3.5 ring-1 ring-ink/[0.04]">
            <p className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40"><span className={`h-2 w-2 rounded-full ${tenant.has_connection?"bg-emerald-500":"bg-ink/20"}`} aria-hidden/> Listing</p>
            <p className="mt-2 truncate text-[13px] font-bold text-ink" title={tenant.listing_name ?? "—"}>{tenant.listing_name ?? "— No listing —"}</p>
            <p className="mt-1 text-[11px] leading-snug text-ink/45">{tenant.has_connection?"Google Business listing connected":"Tenant hasn't linked a location yet"}</p>
          </div>
          <div className="rounded-2xl bg-ink/[0.02] p-3.5 ring-1 ring-ink/[0.04]">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">Last sync</p>
            <p className="mt-2 text-[13px] font-bold text-ink">{tenant.last_synced_at?fmtRelative(tenant.last_synced_at):"never"}</p>
            <p className="mt-1 truncate text-[11px] text-ink/45" title={tenant.last_synced_at?fmtDateTime(tenant.last_synced_at):""}>{tenant.last_synced_at?fmtDateTime(tenant.last_synced_at):"No sync recorded"}</p>
          </div>
          <div className="rounded-2xl bg-sky-50/70 p-3.5 ring-1 ring-sky-100">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-sky-700/60">Reviews</p>
            <p className="mt-2 flex items-baseline gap-1.5 text-[18px] font-bold leading-none text-ink">{tenant.reviews.toLocaleString()} <span className="text-[11px] font-medium text-ink/40">synced</span></p>
            <p className="mt-1 text-[11px] text-ink/45">{tenant.reviews===0?"No reviews indexed yet":"Insights used for AI replies"}</p>
          </div>
          <div className="rounded-2xl bg-violet-50/70 p-3.5 ring-1 ring-violet-100">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-violet-700/60">Content</p>
            <p className="mt-2 flex items-baseline gap-2 text-[13px] font-bold text-ink">
              <span className="rounded-full bg-white px-2 py-1 text-[12px] ring-1 ring-ink/[0.06]">{tenant.posts} posts</span>
              <span className="rounded-full bg-white px-2 py-1 text-[12px] ring-1 ring-ink/[0.06]">{tenant.databanks} banks</span>
            </p>
            <p className="mt-1 text-[11px] text-ink/45">Posts & knowledge banks</p>
          </div>
        </div>
      </div>

      {/* AI Usage — new section */}
      <section className="rounded-2xl border-2 border-white bg-white/85 p-4 shadow-sm sm:p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="flex items-center gap-2 text-[13px] font-bold uppercase tracking-wide text-ink">
              <span className="flex h-7 w-7 items-center justify-center rounded-xl bg-deep-violet/10 text-deep-violet">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M12 3l1.6 3.2 3.4.5-2.5 2.4.6 3.4L12 10.8 8.9 12.5l.6-3.4L7 6.7l3.4-.5L12 3z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/><path d="M5 14l.8 1.5 1.6.2-1.1 1.1.3 1.6L5 17.6l-1.6.8.3-1.6-1.1-1.1 1.6-.2L5 14z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/><path d="M19 13l.7 1.3 1.4.2-1 1 .2 1.4L19 16.2l-1.3.7.2-1.4-1-1 1.4-.2L19 13z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/></svg>
              </span>
              AI usage
              <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[11px] font-bold text-ink/50">per tenant</span>
            </h2>
            <p className="mt-1 text-[11px] leading-relaxed text-ink/45">Tokens, calls and models for this tenant only — spot power use, stalls, and cost.</p>
          </div>
          <div className="flex shrink-0 items-center gap-1.5 rounded-xl bg-ink/[0.04] p-1">
            {[7,30,90].map((d)=>(
              <button key={d} onClick={()=>setUsageDays(d)} className={`rounded-lg px-3 py-1 text-[11px] font-bold transition ${usageDays===d?"bg-deep-violet text-white shadow-sm":"text-ink/50 hover:bg-white hover:text-ink"}`}>{d}d</button>
            ))}
          </div>
        </div>

        {usageLoading ? (
          <div className="mt-4 grid gap-2.5 sm:grid-cols-4">
            {[1,2,3,4].map((i)=><div key={i} className="h-20 animate-pulse rounded-2xl bg-ink/[0.04]" />)}
          </div>
        ) : usage ? (
          <>
            {usageError && <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-[11px] leading-relaxed text-amber-800">{usageError} <button onClick={()=>void loadUsage(usageDays)} className="ml-1 font-bold underline">Retry</button></div>}
            {usage.totals.calls === 0 ? (
          <div className="mt-4 rounded-2xl border border-dashed border-ink/10 bg-ink/[0.02] p-8 text-center">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-white text-ink/30 ring-1 ring-ink/10">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M12 3l1.6 3.2 3.4.5-2.5 2.4.6 3.4L12 10.8 8.9 12.5l.6-3.4L7 6.7l3.4-.5L12 3z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
            </div>
            <p className="mt-3 text-[13px] font-semibold text-ink/70">No AI usage in last {usage.days}d</p>
            <p className="mx-auto mt-1 max-w-[420px] text-[12px] leading-relaxed text-ink/45">This tenant hasn’t triggered LLM calls — no chat, no generation. Nudge to try AI features or check provider keys in <Link href="/llms" className="font-semibold text-deep-violet hover:underline">LLMs</Link>.</p>
          </div>
        ) : (
          <>
            <div className="mt-4 grid gap-2.5 sm:grid-cols-4">
              <div className="rounded-2xl bg-violet-50 px-3.5 py-3 ring-1 ring-violet-100">
                <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-violet-700/60">Total tokens</p>
                <p className="mt-1 text-[18px] font-bold leading-none tabular-nums text-ink">{fmt(usage.totals.total_tokens)}</p>
                <p className="mt-1 text-[11px] text-ink/45">{usage.totals.prompt_tokens.toLocaleString()} prompt · {usage.totals.completion_tokens.toLocaleString()} completion</p>
              </div>
              <div className="rounded-2xl bg-white px-3.5 py-3 ring-1 ring-ink/[0.06]">
                <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">Calls</p>
                <p className="mt-1 text-[18px] font-bold leading-none tabular-nums text-ink">{usage.totals.calls.toLocaleString()}</p>
                <p className="mt-1 text-[11px] text-ink/45">{fmt(usage.totals.total_tokens / Math.max(1, usage.totals.calls))}/call avg · {usage.days}d window</p>
              </div>
              <div className="rounded-2xl bg-white px-3.5 py-3 ring-1 ring-ink/[0.06]">
                <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">Avg latency</p>
                <p className="mt-1 text-[18px] font-bold leading-none tabular-nums text-ink">{fmtMs(usage.totals.avg_latency_ms)}</p>
                <p className="mt-1 text-[11px] text-ink/45">{usage.totals.avg_latency_ms > 3000 ? "Slow — check provider" : usage.totals.avg_latency_ms > 1500 ? "Moderate" : "Fast"}</p>
              </div>
              <div className="rounded-2xl bg-ink/[0.02] px-3.5 py-3 ring-1 ring-ink/[0.04]">
                <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">Progress insight</p>
                {usage.daily.length >= 2 ? (
                  <>
                    {(() => {
                      const mid = Math.floor(usage.daily.length/2);
                      const first = usage.daily.slice(0,mid).reduce((s,d)=>s+d.total_tokens,0);
                      const second = usage.daily.slice(mid).reduce((s,d)=>s+d.total_tokens,0);
                      const growth = first ? Math.round(((second-first)/first)*100) : 0;
                      return (
                        <p className={`mt-1 inline-flex rounded-full px-2 py-1 text-[11px] font-bold ${growth>=0?"bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200":"bg-red-50 text-red-700 ring-1 ring-red-200"}`}>
                          {growth>=0?"↗":"↘"} {Math.abs(growth)}% vs first half
                        </p>
                      );
                    })()}
                    <p className="mt-1 text-[11px] leading-snug text-ink/45">{usage.daily.length} days of activity</p>
                  </>
                ) : (
                  <p className="mt-1 text-[11px] leading-snug text-ink/45">Collecting daily trend… need more days.</p>
                )}
              </div>
            </div>

            <div className="mt-4 grid gap-4 lg:grid-cols-5">
              <div className="lg:col-span-3 rounded-2xl bg-ink/[0.02] p-3.5 ring-1 ring-ink/[0.04]">
                <p className="text-[11px] font-bold uppercase tracking-wide text-ink/50">Daily tokens · {usage.days}d</p>
                {usage.daily.length === 0 ? <p className="mt-2 text-[11px] text-ink/40">No daily points.</p> : <MiniArea points={usage.daily.map((d)=>({x:d.day.slice(5), y:d.total_tokens}))} />}
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {usage.daily.slice(-6).map((d)=>(
                    <span key={d.day} className="rounded-full bg-white px-2 py-1 text-[10px] font-medium text-ink/50 ring-1 ring-ink/[0.06]">{d.day.slice(5)} · {fmt(d.total_tokens)}</span>
                  ))}
                </div>
              </div>
              <div className="lg:col-span-2 space-y-3">
                <div className="rounded-2xl bg-white p-3.5 ring-1 ring-ink/[0.06]">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-ink/50">By model</p>
                  {usage.by_model.length===0 ? <p className="mt-2 text-[11px] text-ink/40">No model breakdown.</p> : (
                    <div className="mt-2 space-y-2">
                      {usage.by_model.slice(0,5).map((m)=>(
                        <div key={m.model}>
                          <div className="flex items-center justify-between gap-2 text-[11px]">
                            <span className="truncate font-semibold text-ink" title={m.model}>{m.model.split(":").pop()}</span>
                            <span className="shrink-0 tabular-nums text-ink/50">{fmt(m.total_tokens)} · {m.calls}</span>
                          </div>
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-ink/[0.06]">
                            <div className="h-full rounded-full bg-deep-violet" style={{width:`${Math.max(3,(m.total_tokens/maxModelTokens)*100)}%`}} />
                          </div>
                        </div>
                      ))}
                      {usage.by_model.length>5 && <p className="text-[11px] text-ink/30">+{usage.by_model.length-5} more models</p>}
                    </div>
                  )}
                </div>
                <div className="rounded-2xl bg-violet-50 p-3.5 ring-1 ring-violet-100">
                  <p className="text-[11px] font-bold uppercase tracking-wide text-violet-700/60">By purpose</p>
                  {usage.by_purpose.length===0 ? <p className="mt-1 text-[11px] text-ink/40">No purpose tagged.</p> : (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {usage.by_purpose.slice(0,6).map((p)=>(
                        <span key={p.purpose} className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 text-[11px] font-semibold text-ink ring-1 ring-violet-200">
                          {p.purpose} <span className="rounded-full bg-violet-500 px-1.5 py-0.5 text-[10px] font-bold text-white">{fmt(p.total_tokens)}</span>
                        </span>
                      ))}
                    </div>
                  )}
                  <Link href="/usage" className="mt-3 inline-flex text-[11px] font-semibold text-deep-violet hover:underline">Open global usage →</Link>
                </div>
              </div>
            </div>
          </>
        )}
          </>
        ) : usageError ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-3 py-3 text-[12px] leading-relaxed text-amber-800">
            {usageError} <button onClick={() => void loadUsage(usageDays)} className="font-bold underline">Retry</button>
            <span className="ml-1 text-amber-700/70">· Restart API to enable full per-tenant history if needed.</span>
          </div>
        ) : null}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Reviews — clickable */}
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-[13px] font-bold uppercase tracking-wide text-ink">
              <span className="flex h-7 w-7 items-center justify-center rounded-xl bg-sky-500/10 text-sky-600">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M12 3.7l1.7 3.4 3.8.6-2.7 2.6.6 3.7L12 12.2 8.6 14l.6-3.7-2.7-2.6 3.8-.6L12 3.7z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"/></svg>
              </span>
              Recent reviews
              <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[11px] font-bold tabular-nums text-ink/50">{tenant.recent_reviews.length}</span>
            </h2>
            <span className="hidden text-[11px] text-ink/30 sm:inline">Click a card to expand</span>
          </div>
          {tenant.recent_reviews.length===0 ? (
            <div className="mt-4 rounded-2xl border border-dashed border-ink/10 bg-ink/[0.02] p-8 text-center">
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-white text-ink/30 ring-1 ring-ink/10">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M12 3.5l2 4 4.5.7-3.2 3.1.8 4.4L12 13.7 7.9 15.7l.8-4.4L5.5 8.2l4.5-.7 2-4z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/></svg>
              </div>
              <p className="mt-3 text-[13px] font-semibold text-ink/70">No reviews synced yet</p>
              <p className="mx-auto mt-1 max-w-[320px] text-[12px] leading-relaxed text-ink/45">Once the listing syncs, Google reviews appear here with sentiment and reply status.</p>
            </div>
          ) : (
            <ul className="mt-4 space-y-3">
              {tenant.recent_reviews.map((r)=>(
                <li key={r.id}>
                  <button
                    type="button"
                    onClick={()=>setSelected(r)}
                    className="group w-full rounded-2xl bg-ink/[0.02] p-3.5 text-left ring-1 ring-ink/[0.04] transition hover:bg-white hover:shadow-sm hover:ring-deep-violet/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Stars rating={r.rating} />
                        <span className="text-[12px] font-semibold text-ink group-hover:text-deep-violet">{r.reviewer ?? "Google user"}</span>
                        <span className="text-ink/20">·</span>
                        <span className="text-[11px] text-ink/45">{r.created_at?fmtRelative(r.created_at):""}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase tracking-wide ring-1 ${sentimentStyle(r.sentiment)}`}>{r.sentiment}</span>
                        {r.replied ? <span className="rounded-full bg-emerald-500 px-2 py-1 text-[10px] font-bold uppercase text-white">replied</span> : <span className="rounded-full bg-white px-2 py-1 text-[10px] font-bold uppercase text-ink/40 ring-1 ring-ink/10">not replied</span>}
                      </div>
                    </div>
                    <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-ink/65 group-hover:text-ink/80">{r.text || <span className="italic text-ink/35">(star rating only — no text)</span>}</p>
                    <p className="mt-2 flex items-center gap-1 text-[11px] font-medium text-deep-violet/70 group-hover:text-deep-violet">
                      View full review
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" aria-hidden><path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"/></svg>
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Posts */}
        <section className="rounded-2xl border-2 border-white bg-white/80 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-[13px] font-bold uppercase tracking-wide text-ink">
              <span className="flex h-7 w-7 items-center justify-center rounded-xl bg-violet-500/10 text-violet-600">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden><rect x="4" y="4" width="16" height="16" rx="2" stroke="currentColor" strokeWidth="1.5"/><path d="M8 9h8M8 12h6M8 15h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
              </span>
              Recent posts
              <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[11px] font-bold tabular-nums text-ink/50">{tenant.recent_posts.length}</span>
            </h2>
            <Link href="/overview" className="hidden text-[11px] font-semibold text-deep-violet hover:underline sm:inline">View overview →</Link>
          </div>
          {tenant.recent_posts.length===0 ? (
            <div className="mt-4 rounded-2xl border border-dashed border-ink/10 bg-ink/[0.02] p-8 text-center">
              <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-full bg-white text-ink/30 ring-1 ring-ink/10">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden><rect x="4" y="4" width="16" height="16" rx="2" stroke="currentColor" strokeWidth="1.5"/><path d="M8 9h8M8 12h6M8 15h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
              </div>
              <p className="mt-3 text-[13px] font-semibold text-ink/70">No posts yet</p>
              <p className="mx-auto mt-1 max-w-[320px] text-[12px] leading-relaxed text-ink/45">Tenant hasn't created posts. Check back after they use the composer.</p>
            </div>
          ) : (
            <ul className="mt-4 space-y-2.5">
              {tenant.recent_posts.map((p)=>(
                <li key={p.id} className="group flex items-center gap-3 rounded-2xl bg-ink/[0.02] p-3.5 ring-1 ring-ink/[0.04] transition hover:bg-white">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-semibold leading-none text-ink group-hover:text-deep-violet" title={p.title || "(untitled)"}>{p.title || <span className="italic text-ink/40">(untitled)</span>}</p>
                    <p className="mt-1.5 text-[11px] text-ink/40" title={p.created_at?fmtDateTime(p.created_at):""}>{p.created_at?`${fmtDate(p.created_at)} · ${fmtRelative(p.created_at)}`:"—"}</p>
                  </div>
                  <span className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide ${statusStyle(p.status)}`}>{p.status}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 rounded-xl bg-ink/[0.02] p-3 ring-1 ring-ink/[0.04]">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-ink/40">Totals for this tenant</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-bold tabular-nums text-ink ring-1 ring-ink/10">{tenant.reviews} reviews</span>
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-bold tabular-nums text-ink ring-1 ring-ink/10">{tenant.posts} posts</span>
              <span className="rounded-full bg-white px-2.5 py-1 text-[11px] font-bold tabular-nums text-ink ring-1 ring-ink/10">{tenant.databanks} banks</span>
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${tenant.has_connection?"bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200":"bg-white text-ink/40 ring-1 ring-ink/10"}`}>{tenant.has_connection?"Connected":"Not connected"}</span>
            </div>
          </div>
        </section>
      </div>

      {/* Review modal */}
      {selected && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button type="button" aria-label="Close review" onClick={()=>setSelected(null)} className="absolute inset-0 bg-ink/40 backdrop-blur-sm" />
          <div role="dialog" aria-modal="true" aria-labelledby="review-title" className="relative max-h-[85vh] w-full max-w-[560px] overflow-auto rounded-2xl border-2 border-white bg-white p-5 shadow-xl">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p id="review-title" className="flex items-center gap-2 text-[13px] font-bold text-ink">
                  <Stars rating={selected.rating} />
                  <span className="rounded-full bg-ink/[0.06] px-2 py-0.5 text-[11px] font-bold">{selected.rating}★</span>
                  <span className={`rounded-full px-2 py-1 text-[10px] font-bold uppercase ring-1 ${sentimentStyle(selected.sentiment)}`}>{selected.sentiment}</span>
                </p>
                <p className="mt-1 text-[12px] font-semibold text-ink">{selected.reviewer ?? "Google user"}</p>
                <p className="text-[11px] text-ink/45">{selected.created_at?fmtDateTime(selected.created_at):""} · {selected.created_at?fmtRelative(selected.created_at):""}</p>
              </div>
              <div className="flex items-center gap-2">
                {selected.replied ? <span className="rounded-full bg-emerald-500 px-2.5 py-1 text-[11px] font-bold uppercase text-white">Replied</span> : <span className="rounded-full bg-ink/[0.06] px-2.5 py-1 text-[11px] font-bold uppercase text-ink/50">Not replied</span>}
                <button onClick={()=>setSelected(null)} className="rounded-xl bg-ink px-3 py-1.5 text-[12px] font-bold text-white hover:bg-ink/90">Close</button>
              </div>
            </div>
            <div className="mt-4 rounded-2xl bg-ink/[0.03] p-4 ring-1 ring-ink/[0.06]">
              <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink/80">{selected.text || "(No text — star rating only)"}</p>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={async()=>{ try{ await navigator.clipboard.writeText(selected.text || ""); }catch{}}} className="rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 hover:bg-ink/[0.03]">Copy text</button>
              <span className="rounded-full bg-white px-3 py-2 text-[11px] text-ink/40 ring-1 ring-ink/[0.06]">ID {selected.id.slice(0,8)}…</span>
              {selected.created_at && <span className="rounded-full bg-white px-3 py-2 text-[11px] text-ink/40 ring-1 ring-ink/[0.06]">{fmtDateTime(selected.created_at)}</span>}
            </div>
            <p className="mt-3 text-center text-[11px] text-ink/30">Click outside to close · Esc</p>
          </div>
        </div>
      )}

      <p className="pb-2 text-center text-[11px] text-ink/25">Tenant ID {tenant.id} · Read-only view · Data live from PostgreSQL</p>
    </div>
  );
}
