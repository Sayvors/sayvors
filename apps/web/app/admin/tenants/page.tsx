"use client";

import { useEffect, useState } from "react";
import { adminFetch } from "@/lib/admin-api";
import {
  ErrorState,
  PageHeader,
  Panel,
  Pill,
  Table,
  TableScroll,
  Td,
  Th,
} from "../admin-ui";
import LogoLoader from "@/components/LogoLoader";

interface Tenant {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  email_verified: boolean;
  created_at: string | null;
  has_connection: boolean;
  listing_name: string | null;
  last_synced_at: string | null;
  reviews: number;
  posts: number;
  databanks: number;
}

interface TenantDetail extends Tenant {
  recent_reviews: { rating?: number; text?: string | null; reviewer?: string | null }[];
  recent_posts: { title?: string; status?: string }[];
  /** Present on the detail endpoint, absent from the list rows. */
  plan?: string;
  ai_balance_cents?: number | null;
  ai_spent_30d_cents?: number;
}

/** Dollars from integer cents. Money is the one field a stray zero breaks. */
function usd(cents: number | null | undefined): string {
  if (typeof cents !== "number" || !Number.isFinite(cents)) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

/** Shape of GET /api/v1/admin/tenants/{id}/usage (llm.usage.get_tenant_summary). */
interface TenantUsage {
  days: number;
  totals: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    avg_latency_ms: number;
  };
  by_model: { model: string; api_model: string; calls: number; total_tokens: number; avg_latency_ms: number }[];
  by_purpose: { purpose: string; calls: number; total_tokens: number }[];
  daily: { day: string; total_tokens: number; prompt_tokens: number; completion_tokens: number; avg_latency_ms: number; calls: number }[];
}

export default function AdminTenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TenantDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Plan grant form — per open tenant, reset when a different row is opened.
  const [planForm, setPlanForm] = useState({ plan: "pro", credit: "2000", note: "" });
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  /**
   * A completed action is a fact, not a failure. Sharing the error slot made
   * "Granted pro. New AI balance $20.00." render inside the coral error banner
   * with a Try again button -- the opposite of what just happened.
   */
  const [notice, setNotice] = useState<string | null>(null);

  /** Per-tenant AI usage, fetched alongside the detail. */
  const [usage, setUsage] = useState<TenantUsage | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const d = await adminFetch<{ items: Tenant[] }>("/api/v1/admin/tenants?limit=200");
      setTenants(d.items ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load tenants.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function toggleOpen(id: string) {
    if (openId === id) {
      setOpenId(null);
      setDetail(null);
      return;
    }
    setOpenId(id);
    setDetail(null);
    setDetailLoading(true);
    setUsage(null);
    try {
      // Detail and usage are independent; a usage failure must not blank the
      // detail the operator opened the row for.
      const [d, u] = await Promise.allSettled([
        adminFetch<TenantDetail>(`/api/v1/admin/tenants/${id}`),
        adminFetch<TenantUsage>(`/api/v1/admin/tenants/${id}/usage`),
      ]);
      if (d.status === "fulfilled") setDetail(d.value);
      else setError(d.reason instanceof Error ? d.reason.message : "Could not load tenant.");
      if (u.status === "fulfilled") setUsage(u.value);
    } finally {
      setDetailLoading(false);
    }
    // A different tenant gets a fresh form, so a stale note never rides along
    // to the next grant -- and a success from the previous one must not still
    // be sitting there when the next row opens.
    setPlanForm({ plan: "pro", credit: "2000", note: "" });
    setPlanError(null);
    setNotice(null);
  }

  /**
   * Record a plan purchase for this tenant.
   *
   * A first-time Pro grant bundles $20 of AI credits automatically (the
   * backend owns that), so the operator should NOT also type 2000 here --
   * doing so double-funds. The default is 0 and the hint says why, because
   * this is the kind of field people fill in by reflex.
   */
  async function grantPlan() {
    if (!openId) return;
    const cents = Math.round(parseFloat(planForm.credit || "0") * 100);
    if (!Number.isFinite(cents) || cents < 0 || cents > 1_000_000) {
      setPlanError("Credit must be a dollar amount between 0 and 10,000.");
      return;
    }
    setPlanBusy(true);
    setPlanError(null);
    try {
      const res = await adminFetch<{ plan: string; balance_dollars: number }>(
        `/api/v1/admin/tenants/${openId}/plan`,
        {
          method: "POST",
          body: JSON.stringify({
            plan: planForm.plan,
            add_credit_cents: cents,
            note: planForm.note.trim() || undefined,
          }),
        }
      );
      setPlanForm({ plan: "pro", credit: "2000", note: "" });
      // Reload the row so the new plan and balance are facts, not hopes.
      await load();
      if (openId) {
        try {
          setDetail(await adminFetch<TenantDetail>(`/api/v1/admin/tenants/${openId}`));
        } catch {
          /* the list already refreshed */
        }
      }
      setNotice(`Granted ${res.plan}. New AI balance $${res.balance_dollars.toFixed(2)}.`);
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : "Could not grant the plan.");
    } finally {
      setPlanBusy(false);
    }
  }

  const q = search.trim().toLowerCase();
  const filtered = q
    ? tenants.filter((t) =>
        t.email.toLowerCase().includes(q) ||
        `${t.first_name ?? ""} ${t.last_name ?? ""}`.toLowerCase().includes(q) ||
        (t.listing_name ?? "").toLowerCase().includes(q))
    : tenants;

  if (loading) return <div className="flex justify-center py-24"><LogoLoader size={30} /></div>;

  return (
    <div className="admin-ui">
      <PageHeader
        title="Tenants"
        actions={
          <>
            {/* Only meaningful once a filter is active. "12 of 12 shown"
                unfiltered is noise that looks like a fact. */}
            {q && (
              <span className="text-admin-base text-ink/55">
                <span className="font-bold tabular-nums text-ink">
                  {filtered.length}
                </span>{" "}
                of <span className="tabular-nums">{tenants.length}</span> match
              </span>
            )}
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search email / name / listing"
              aria-label="Search tenants"
              type="search"
              className="input-field w-full max-w-64"
            />
          </>
        }
      />
      {notice && (
        <div
          role="status"
          className="mb-[var(--ad-m)] flex items-start justify-between gap-[var(--ad-s)] rounded-admin-card border border-emerald-400/40 bg-emerald-50 p-[var(--ad-s)]"
        >
          <p className="text-admin-base font-semibold text-emerald-800">{notice}</p>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss"
            className="admin-btn shrink-0 border border-emerald-400/40 px-[var(--ad-2xs)] py-1 text-admin-micro text-emerald-800"
          >
            Dismiss
          </button>
        </div>
      )}
      {error && (
        <div className="mb-[var(--ad-m)]">
          <ErrorState title="Tenants unavailable" detail={error} onRetry={() => void load()} />
        </div>
      )}      {planError && (
        <div className="mb-[var(--ad-m)]">
          <ErrorState title="Plan grant failed" detail={planError} />
        </div>
      )}

      {/* TableScroll: overflow-x-auto, not overflow-hidden. Hidden CLIPPED the
          Posts / Databanks / Last sync columns at 390px, leaving them
          unreachable. overflow-y-hidden still holds the rounded corners. */}
      <TableScroll>
        <Table minWidth={760}>
          <thead>
            <tr className="border-b border-ink/[0.06]">
              <Th>Tenant</Th>
              <Th>Listing</Th>
              <Th align="right">Reviews</Th>
              <Th align="right">Posts</Th>
              <Th>Last sync</Th>
              <Th>Status</Th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-[var(--ad-s)] py-[var(--ad-m)] text-center text-admin-base text-ink/45">
                  {q ? `No tenant matches "${search}".` : "No tenants yet."}
                </td>
              </tr>
            )}
            {filtered.map((t) => (
              <>
                <tr
                  key={t.id}
                  onClick={() => void toggleOpen(t.id)}
                  className="cursor-pointer border-b border-ink/[0.04] transition hover:bg-deep-violet/[0.03]"
                >
                  <Td>
                    <div className="font-semibold text-ink">{t.email}</div>
                    <div className="text-admin-micro text-ink/50">{[t.first_name, t.last_name].filter(Boolean).join(" ") || "—"}</div>
                  </Td>
                  <Td className="text-ink/70">{t.has_connection ? t.listing_name ?? "connected" : <span className="text-ink/35">not connected</span>}</Td>
                  <Td align="right" className="font-bold text-ink">{t.reviews.toLocaleString()}</Td>
                  <Td align="right" className="font-bold text-ink">{t.posts.toLocaleString()}</Td>
                  <Td className="text-ink/55">{t.last_synced_at ? new Date(t.last_synced_at).toLocaleDateString() : "never"}</Td>
                  <Td>
                    <Pill tone={t.email_verified ? "ok" : "warn"}>
                      {t.email_verified ? "Verified" : "Unverified"}
                    </Pill>
                  </Td>
                </tr>
                {openId === t.id && (
                  <tr key={`${t.id}-detail`} className="border-b border-ink/[0.04] bg-deep-violet/[0.02]">
                    <td colSpan={6} className="px-4 py-4">
                      {detailLoading ? (
                        <LogoLoader size={18} />
                      ) : detail ? (
                        <>
                          {/* Plan + AI balance first: these are the fields an
                              operator acts on, and they were missing entirely. */}
                          <div className="grid grid-cols-2 gap-3">
                            <div className="rounded-admin-ctl border border-ink/[0.07] p-[var(--ad-xs)]">
                              <p className="text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/50">
                                Plan
                              </p>
                              <p className="text-admin-base font-bold text-ink">
                                {(detail.plan ?? "free").toUpperCase()}
                              </p>
                            </div>
                            <div className="rounded-admin-ctl border border-ink/[0.07] p-[var(--ad-xs)]">
                              <p className="text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/50">
                                AI balance
                              </p>
                              <p className="text-admin-base font-bold tabular-nums text-ink">
                                {usd(detail.ai_balance_cents)}
                              </p>
                              <p className="text-admin-micro text-ink/45">
                                spent 30d: {usd(detail.ai_spent_30d_cents)}
                              </p>
                            </div>
                          </div>

                          {planError && (
                            <p role="alert" className="mt-[var(--ad-xs)] rounded-admin-ctl bg-coral/10 px-[var(--ad-xs)] py-[var(--ad-2xs)] text-admin-base font-medium text-coral">
                              {planError}
                            </p>
                          )}
                          {usage && (
                            <div className="mt-[var(--ad-xs)] space-y-[var(--ad-xs)] rounded-admin-ctl border border-ink/[0.07] p-[var(--ad-xs)]">
                              <p className="text-admin-base font-bold uppercase tracking-wide text-ink">
                                AI usage ({usage.days}d)
                              </p>
                              <div className="grid grid-cols-3 gap-[var(--ad-2xs)]">
                                {(
                                  [
                                    ["Calls", usage.totals.calls],
                                    ["Tokens", usage.totals.total_tokens],
                                    ["Avg ms", usage.totals.avg_latency_ms],
                                  ] as [string, number][]
                                ).map(([k, v]) => (
                                  <div key={k}>
                                    <p className="text-admin-micro text-ink/45">{k}</p>
                                    <p className="text-admin-base font-bold tabular-nums text-ink">
                                      {v.toLocaleString()}
                                    </p>
                                  </div>
                                ))}
                              </div>
                              {usage.by_model.length > 0 && (
                                <div>
                                  <p className="mb-[var(--ad-3xs)] text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/45">
                                    By model
                                  </p>
                                  <ul className="space-y-[var(--ad-3xs)]">
                                    {usage.by_model.slice(0, 5).map((m) => (
                                      <li key={m.api_model} className="flex items-baseline justify-between gap-[var(--ad-2xs)] text-admin-base">
                                        <span className="min-w-0 truncate text-ink/70">{m.api_model}</span>
                                        <span className="tabular-nums text-ink">
                                          {m.calls.toLocaleString()} calls ·{" "}
                                          {m.total_tokens.toLocaleString()} tok
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {usage.by_purpose.length > 0 && (
                                <div>
                                  <p className="mb-[var(--ad-3xs)] text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/45">
                                    By purpose
                                  </p>
                                  <ul className="space-y-[var(--ad-3xs)]">
                                    {usage.by_purpose.slice(0, 5).map((p) => (
                                      <li key={p.purpose} className="flex items-baseline justify-between gap-[var(--ad-2xs)] text-admin-base">
                                        <span className="min-w-0 truncate text-ink/70">
                                          {p.purpose.replace(/_/g, " ")}
                                        </span>
                                        <span className="tabular-nums text-ink">
                                          {p.calls.toLocaleString()} calls
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {usage.daily.length > 0 && (
                                <div>
                                  <p className="mb-[var(--ad-3xs)] text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/45">
                                    Daily
                                  </p>
                                  <ul className="space-y-[var(--ad-3xs)]">
                                    {usage.daily.slice(-7).map((d) => (
                                      <li key={d.day} className="flex items-baseline justify-between gap-[var(--ad-2xs)] text-admin-base">
                                        <span className="text-ink/60">{d.day}</span>
                                        <span className="tabular-nums text-ink">
                                          {d.calls.toLocaleString()} calls ·{" "}
                                          {d.total_tokens.toLocaleString()} tok
                                        </span>
                                      </li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                            </div>
                          )}

                          <div className="mt-[var(--ad-xs)] space-y-[var(--ad-xs)] rounded-admin-ctl border border-deep-violet/20 bg-deep-violet/[0.03] p-[var(--ad-xs)]">
                            <p className="text-admin-base font-bold uppercase tracking-wide text-deep-violet">
                              Grant plan
                            </p>
                            <div className="flex flex-wrap items-center gap-[var(--ad-2xs)]">
                              <div className="flex gap-[var(--ad-3xs)]">
                                {["free", "pro"].map((pl) => (
                                  <button
                                    key={pl}
                                    type="button"
                                    aria-pressed={planForm.plan === pl}
                                    onClick={() => setPlanForm({ ...planForm, plan: pl })}
                                    className={`admin-btn border px-[var(--ad-xs)] py-1 text-admin-micro ${
                                      planForm.plan === pl
                                        ? "border-deep-violet bg-deep-violet text-white"
                                        : "border-ink/10 text-ink/70"
                                    }`}
                                  >
                                    {pl.toUpperCase()}
                                  </button>
                                ))}
                              </div>
                              <input
                                value={planForm.credit}
                                onChange={(e) => setPlanForm({ ...planForm, credit: e.target.value })}
                                placeholder="Credit USD"
                                aria-label="Credit to add in dollars"
                                inputMode="decimal"
                                className="input-field w-28"
                              />
                              <input
                                value={planForm.note}
                                onChange={(e) => setPlanForm({ ...planForm, note: e.target.value })}
                                placeholder="Note (optional)"
                                aria-label="Note for this grant"
                                className="input-field min-w-0 flex-1"
                              />
                            </div>
                            {/* The backend bundles $20 on a first Pro grant; saying
                                so here stops the operator double-funding by reflex. */}
                            <p className="text-admin-micro text-ink/45">
                              A first Pro grant adds $20 of AI credits automatically.
                              Leave credit at 0 unless you mean to add more.
                            </p>
                            <button
                              type="button"
                              onClick={() => void grantPlan()}
                              disabled={planBusy}
                              aria-busy={planBusy}
                              className="admin-btn bg-deep-violet text-white hover:bg-deep-violet/90 disabled:opacity-40"
                            >
                              {planBusy ? "Granting…" : "Grant plan"}
                            </button>
                          </div>

                          <div className="mt-[var(--ad-xs)] grid gap-4 sm:grid-cols-2">
                            <div>
                              <p className="text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/50">
                                Recent reviews
                              </p>
                              {(detail.recent_reviews ?? []).length === 0 ? (
                                <p className="mt-[var(--ad-3xs)] text-admin-base text-ink/40">none</p>
                              ) : (
                                <ul className="mt-[var(--ad-3xs)] space-y-[var(--ad-3xs)]">
                                  {detail.recent_reviews.slice(0, 5).map((r, i) => (
                                    <li key={i} className="text-admin-base text-ink/75">
                                      {"★".repeat(r.rating ?? 0)} {r.reviewer ?? "—"}:{" "}
                                      {(r.text ?? "").slice(0, 60) || "(no text)"}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                            <div>
                              <p className="text-admin-micro font-bold uppercase tracking-[0.12em] text-ink/50">
                                Recent posts
                              </p>
                              {(detail.recent_posts ?? []).length === 0 ? (
                                <p className="mt-[var(--ad-3xs)] text-admin-base text-ink/40">none</p>
                              ) : (
                                <ul className="mt-[var(--ad-3xs)] space-y-[var(--ad-3xs)]">
                                  {detail.recent_posts.slice(0, 5).map((p, i) => (
                                    <li key={i} className="text-admin-base text-ink/75">
                                      {p.title ?? "Untitled"} — {p.status ?? "?"}
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                          </div>
                        </>
                      ) : (
                        <p className="text-admin-base text-ink/40">Could not load detail.</p>
                      )}
                    </td>
                  </tr>
                )}
              </>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-[12px] text-ink/35">No tenants match.</td></tr>
            )}
          </tbody>
        </Table>
      </TableScroll>
    </div>
  );
}
