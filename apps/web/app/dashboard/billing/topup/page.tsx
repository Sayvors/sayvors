"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Breadcrumbs from "@/components/Breadcrumbs";
import { useI18n } from "@/lib/i18n/I18nProvider";
import {
  createBillingRequest,
  getBudget,
  getEntitlements,
  getPlans,
  listBillingRequests,
  type BillingRequest,
  type BillingRequestKind,
} from "@/lib/api-billing";
import { queryKeys } from "@/lib/query-keys";

const MESSAGE_PACKS = [500, 1000];
const CREDIT_PACKS = [1000, 2500, 5000, 10000]; // cents: $10/$25/$50/$100
const CHANNEL_PACKS = [1, 3, 5];

function fmtCents(cents: number, locale: string): string {
  return `$${new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US", {
    maximumFractionDigits: 2,
  }).format(cents / 100)}`;
}

function fmtNum(n: number, locale: string): string {
  return new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US", {
    maximumFractionDigits: 0,
  }).format(n);
}

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

const PLAN_SLUG_KEYS: Record<string, "trial" | "free" | "starter" | "pro" | "growth" | "enterprise"> = {
  "free-trial": "trial",
  free: "free",
  starter: "starter",
  pro: "pro",
  growth: "growth",
  enterprise: "enterprise",
};

function statusStyle(status: BillingRequest["status"]): string {
  if (status === "approved") return "bg-emerald-100 text-emerald-700";
  if (status === "rejected") return "bg-red-100 text-red-700";
  return "bg-amber-100 text-amber-700";
}

function requestSummary(
  request: BillingRequest,
  kindLabels: Record<string, string>,
  planDisplay: (slug: string | null | undefined) => string,
  locale: string,
): string {
  if (request.kind === "ai_credit") return fmtCents(request.amount ?? 0, locale);
  if (request.kind === "plan") return planDisplay(request.plan_slug);
  const unit = request.kind === "messages" ? kindLabels.messages : kindLabels.channels;
  return `${fmtNum(request.amount ?? 0, locale)} ${unit}`;
}

export default function TopUpPage() {
  const { t, locale } = useI18n();
  const u = t.dashboard.billing.topup;
  const planNames = t.dashboard.plans.planNames;
  const planDisplay = (slug: string | null | undefined): string => {
    const key = slug ? PLAN_SLUG_KEYS[slug] : undefined;
    return (key ? planNames[key] : undefined) ?? slug ?? "—";
  };
  const queryClient = useQueryClient();
  const entitlements = useQuery({
    queryKey: queryKeys.billing.entitlements(),
    queryFn: getEntitlements,
    staleTime: 30_000,
  });
  const budget = useQuery({ queryKey: queryKeys.billing.budget(), queryFn: getBudget, staleTime: 30_000 });
  const plans = useQuery({ queryKey: queryKeys.billing.plans(), queryFn: getPlans, staleTime: 300_000 });
  const requests = useQuery({ queryKey: ["billing", "requests"], queryFn: listBillingRequests });

  const [messagePack, setMessagePack] = useState(500);
  const [messageCustom, setMessageCustom] = useState("");
  const [creditPack, setCreditPack] = useState(2500);
  const [creditCustom, setCreditCustom] = useState("");
  const [channelPack, setChannelPack] = useState(1);
  const [channelCustom, setChannelCustom] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<BillingRequestKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const planSlug = entitlements.data?.plan_slug ?? "";
  const messageLimit = entitlements.data?.max_messages_per_month ?? null;
  const usedMessages = entitlements.data?.messages_used_this_month ?? 0;
  const balance = budget.data?.balance_cents ?? 0;
  const scPerUsd = budget.data?.credits_per_usd ?? 1000;
  // Fallback keeps old API builds (no balance_credits yet) correct instead of
  // rendering "0 SC" next to a real dollar balance.
  const balanceCredits =
    budget.data?.balance_credits ?? (balance / 100) * scPerUsd;
  const currentPlanData = (plans.data ?? []).find(
    (plan) => plan.slug === (entitlements.data?.plan_slug ?? ""),
  );
  const includedCreditSc = currentPlanData
    ? (currentPlanData.included_credit_cents / 100) * scPerUsd
    : 0;

  async function submit(kind: BillingRequestKind, amount: number | null, plan_slug?: string | null) {
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      const result = await createBillingRequest({
        kind,
        amount,
        plan_slug: plan_slug ?? null,
        note: note.trim() || null,
      });
      setNotice(
        result.duplicate ? u.duplicate : u.sent,
      );
      setNote("");
      await queryClient.invalidateQueries({ queryKey: ["billing", "requests"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : u.sendFailed);
    } finally {
      setBusy(null);
    }
  }

  function parseCustom(value: string): number | null {
    const n = Number(value.replace(/[^0-9.]/g, ""));
    return Number.isFinite(n) && n > 0 ? n : null;
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        <Breadcrumbs items={[{ label: t.nav.billing, href: "/dashboard/billing" }, { label: u.title }]} />
        <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight text-ink dark:text-fog">{u.title}</h1>
            <p className="mt-1 text-[13px] leading-relaxed text-ink/55 dark:text-fog/55">
              {u.subtitle}
            </p>
          </div>
          <Link
            href="/dashboard/plans"
            className="rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink/60 transition hover:border-deep-violet/30 hover:text-deep-violet dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60"
          >
            {u.viewPlans}
          </Link>
        </div>

        {(error || notice) && (
          <p
            role="status"
            className={`mt-4 rounded-xl px-3.5 py-2.5 text-[12px] leading-relaxed ${
              error ? "bg-coral/10 text-coral" : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
            }`}
          >
            {error ?? notice}
          </p>
        )}

        {/* current usage */}
        <div className="mt-5 grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">{u.msgsThisMonth}</p>
            <p className="mt-1 text-[18px] font-bold tabular-nums text-ink dark:text-fog">
              {fmtNum(usedMessages, locale)}
              <span className="text-[12px] font-medium text-ink/40 dark:text-fog/40">
                {" / "}
                {messageLimit == null ? u.unlimited : fmtNum(messageLimit, locale)}
              </span>
            </p>
          </div>
          <div className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">{u.aiBalance}</p>
            <div className="mt-1 flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/Sayvors_Credits.png" alt="" width={26} height={26} className="h-[26px] w-[26px] shrink-0" />
              <p className="text-[18px] font-bold tabular-nums text-ink dark:text-fog">
                {fmtNum(Math.round(balanceCredits), locale)}
                <span className="ml-1 text-[11px] font-semibold text-ink/40 dark:text-fog/40">SC</span>
              </p>
            </div>
          </div>
          <div className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">{u.plan}</p>
            <p className="mt-1 text-[18px] font-bold text-ink dark:text-fog">{planDisplay(planSlug) || "—"}</p>
            <p className="mt-1 text-[10.5px] leading-snug text-ink/40 dark:text-fog/40">
              {messageLimit == null
                ? u.unlimitedMsgs
                : fill(u.msgsPerMonth, { limit: fmtNum(messageLimit, locale) })}
              {currentPlanData
                ? fill(u.included, { amount: fmtNum(Math.round(includedCreditSc), locale) })
                : ""}
            </p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          {/* messages */}
          <section className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">{u.msgsTitle}</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
              {u.msgsDesc}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {MESSAGE_PACKS.map((pack) => (
                <button
                  key={pack}
                  type="button"
                  onClick={() => { setMessagePack(pack); setMessageCustom(""); }}
                  className={`rounded-xl px-3 py-2 text-[12px] font-semibold transition ${
                    messagePack === pack && !messageCustom
                      ? "bg-deep-violet text-white"
                      : "border border-ink/[0.08] bg-white text-ink/60 hover:border-deep-violet/40 hover:text-deep-violet dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60"
                  }`}
                >
                  +{fmtNum(pack, locale)}
                </button>
              ))}
              <input
                value={messageCustom}
                onChange={(e) => setMessageCustom(e.target.value)}
                inputMode="numeric"
                placeholder={u.custom}
                aria-label={u.customMsgsAria}
                className="w-28 rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              />
            </div>
            <button
              type="button"
              onClick={() => void submit("messages", parseCustom(messageCustom) ?? messagePack)}
              disabled={busy !== null}
              className="mt-3 w-full rounded-xl bg-deep-violet px-3 py-2.5 text-[12.5px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
            >
              {busy === "messages" ? u.sending : fill(u.requestMsgs, { amount: fmtNum(parseCustom(messageCustom) ?? messagePack, locale) })}
            </button>
          </section>

          {/* AI credit */}
          <section className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">{u.creditTitle}</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
              {u.creditDesc}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {CREDIT_PACKS.map((cents) => (
                <button
                  key={cents}
                  type="button"
                  onClick={() => { setCreditPack(cents); setCreditCustom(""); }}
                  className={`rounded-xl px-3 py-2 text-[12px] font-semibold transition ${
                    creditPack === cents && !creditCustom
                      ? "bg-deep-violet text-white"
                      : "border border-ink/[0.08] bg-white text-ink/60 hover:border-deep-violet/40 hover:text-deep-violet dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60"
                  }`}
                >
                  {fmtCents(cents, locale)}
                </button>
              ))}
              <input
                value={creditCustom}
                onChange={(e) => setCreditCustom(e.target.value)}
                inputMode="decimal"
                placeholder={u.customCredit}
                aria-label={u.customCreditAria}
                className="w-28 rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              />
            </div>
            <button
              type="button"
              onClick={() => {
                const custom = parseCustom(creditCustom);
                void submit("ai_credit", custom ? Math.round(custom * 100) : creditPack);
              }}
              disabled={busy !== null}
              className="mt-3 w-full rounded-xl bg-deep-violet px-3 py-2.5 text-[12.5px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
            >
              {busy === "ai_credit"
                ? u.sending
                : fill(u.requestCredit, { amount: parseCustom(creditCustom) ? fmtCents(Math.round((parseCustom(creditCustom) ?? 0) * 100), locale) : fmtCents(creditPack, locale) })}
            </button>
          </section>

          {/* channels */}
          <section className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">{u.channelsTitle}</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
              {u.channelsDesc}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {CHANNEL_PACKS.map((pack) => (
                <button
                  key={pack}
                  type="button"
                  onClick={() => { setChannelPack(pack); setChannelCustom(""); }}
                  className={`rounded-xl px-3 py-2 text-[12px] font-semibold transition ${
                    channelPack === pack && !channelCustom
                      ? "bg-deep-violet text-white"
                      : "border border-ink/[0.08] bg-white text-ink/60 hover:border-deep-violet/40 hover:text-deep-violet dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60"
                  }`}
                >
                  +{fmtNum(pack, locale)}
                </button>
              ))}
              <input
                value={channelCustom}
                onChange={(e) => setChannelCustom(e.target.value)}
                inputMode="numeric"
                placeholder={u.custom}
                aria-label={u.customChannelAria}
                className="w-28 rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              />
            </div>
            <button
              type="button"
              onClick={() => void submit("channels", parseCustom(channelCustom) ?? channelPack)}
              disabled={busy !== null}
              className="mt-3 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2.5 text-[12.5px] font-bold text-ink/70 transition hover:border-deep-violet/40 hover:text-deep-violet disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog/70"
            >
              {busy === "channels"
                ? u.sending
                : fill((parseCustom(channelCustom) ?? channelPack) === 1 ? u.requestChannelOne : u.requestChannelMany, { amount: fmtNum(parseCustom(channelCustom) ?? channelPack, locale) })}
            </button>
          </section>

          {/* enterprise */}
          <section className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">{u.entTitle}</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
              {u.entDesc}
              {planSlug === "enterprise" ? ` ${u.entAlready}` : ""}
            </p>
            <button
              type="button"
              onClick={() => void submit("plan", null, "enterprise")}
              disabled={busy !== null || planSlug === "enterprise"}
              className="mt-3 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2.5 text-[12.5px] font-bold text-ink/70 transition hover:border-deep-violet/40 hover:text-deep-violet disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog/70"
            >
              {busy === "plan" ? u.sending : planSlug === "enterprise" ? u.currentPlan : u.requestEnt}
            </button>
          </section>
        </div>

        {/* note + history */}
        <section className="mt-6 rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
          <label className="block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45 dark:text-fog/45">
            {u.noteLabel}
          </label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={500}
            rows={2}
            placeholder={u.notePh}
            className="mt-1.5 w-full resize-none rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12.5px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
          />
        </section>

        <section className="mt-6">
          <h2 className="text-[13px] font-bold text-ink dark:text-fog">{u.historyTitle}</h2>
          {requests.isLoading ? (
            <p className="mt-2 text-[12px] text-ink/40 dark:text-fog/40">{u.historyLoading}</p>
          ) : (requests.data ?? []).length === 0 ? (
            <p className="mt-2 rounded-2xl border border-dashed border-ink/[0.1] p-5 text-center text-[12px] text-ink/45 dark:border-fog/[0.12] dark:text-fog/45">
              {u.historyEmpty}
            </p>
          ) : (
            <ul className="mt-2 space-y-2">
              {(requests.data ?? []).map((request) => (
                <li
                  key={request.id}
                  className="flex flex-wrap items-center gap-2 rounded-xl border border-ink/[0.07] bg-white px-3.5 py-2.5 text-[12px] dark:border-fog/[0.08] dark:bg-ink/60"
                >
                  <span className="font-semibold text-ink dark:text-fog">{(u.kinds as Record<string, string>)[request.kind] ?? request.kind}</span>
                  <span className="text-ink/55 dark:text-fog/55">{requestSummary(request, u.kinds, planDisplay, locale)}</span>
                  <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${statusStyle(request.status)}`}>
                    {(u.statuses as Record<string, string>)[request.status] ?? request.status}
                  </span>
                  <span className="w-full text-[10.5px] text-ink/40 dark:text-fog/40">
                    {new Date(request.created_at).toLocaleString(locale === "ar" ? "ar-SA" : "en-US")}
                    {request.decision_note ? ` · ${request.decision_note}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
