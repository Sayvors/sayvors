"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Breadcrumbs from "@/components/Breadcrumbs";
import {
  createBillingRequest,
  getBudget,
  getEntitlements,
  listBillingRequests,
  type BillingRequest,
  type BillingRequestKind,
} from "@/lib/api-billing";
import { queryKeys } from "@/lib/query-keys";

const MESSAGE_PACKS = [500, 1000];
const CREDIT_PACKS = [1000, 2500, 5000, 10000]; // cents: $10/$25/$50/$100
const CHANNEL_PACKS = [1, 3, 5];

function fmtCents(cents: number): string {
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function statusStyle(status: BillingRequest["status"]): string {
  if (status === "approved") return "bg-emerald-100 text-emerald-700";
  if (status === "rejected") return "bg-red-100 text-red-700";
  return "bg-amber-100 text-amber-700";
}

const KIND_LABEL: Record<string, string> = {
  messages: "WhatsApp messages",
  ai_credit: "AI credit",
  channels: "Channels",
  plan: "Plan",
};

function requestSummary(request: BillingRequest): string {
  if (request.kind === "ai_credit") return fmtCents(request.amount ?? 0);
  if (request.kind === "plan") return request.plan_slug ?? "Plan";
  return `${(request.amount ?? 0).toLocaleString()} ${request.kind === "messages" ? "messages" : "channels"}`;
}

export default function TopUpPage() {
  const queryClient = useQueryClient();
  const entitlements = useQuery({
    queryKey: queryKeys.billing.entitlements(),
    queryFn: getEntitlements,
    staleTime: 30_000,
  });
  const budget = useQuery({ queryKey: queryKeys.billing.budget(), queryFn: getBudget, staleTime: 30_000 });
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

  const currentPlan = entitlements.data?.plan_name ?? "";
  const planSlug = entitlements.data?.plan_slug ?? "";
  const messageLimit = entitlements.data?.max_messages_per_month ?? null;
  const usedMessages = entitlements.data?.messages_used_this_month ?? 0;
  const balance = budget.data?.balance_cents ?? 0;
  const balanceCredits = budget.data?.balance_credits ?? 0;
  const scPerUsd = budget.data?.credits_per_usd ?? 1000;

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
        result.duplicate
          ? "You already have this request pending — an operator will review it shortly."
          : "Request sent. An operator will review it and you'll get a notification.",
      );
      setNote("");
      await queryClient.invalidateQueries({ queryKey: ["billing", "requests"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not send the request.");
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
        <Breadcrumbs items={[{ label: "Billing", href: "/dashboard/billing" }, { label: "Top up" }]} />
        <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[22px] font-bold tracking-tight text-ink dark:text-fog">Top up</h1>
            <p className="mt-1 text-[13px] leading-relaxed text-ink/55 dark:text-fog/55">
              Payments are not live yet. Choose what you need and an operator will approve it.
            </p>
          </div>
          <Link
            href="/dashboard/plans"
            className="rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] font-semibold text-ink/60 transition hover:border-deep-violet/30 hover:text-deep-violet dark:border-fog/[0.1] dark:bg-ink dark:text-fog/60"
          >
            View plans
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
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">Messages this month</p>
            <p className="mt-1 text-[18px] font-bold tabular-nums text-ink dark:text-fog">
              {usedMessages.toLocaleString()}
              <span className="text-[12px] font-medium text-ink/40 dark:text-fog/40">
                {" / "}
                {messageLimit == null ? "unlimited" : messageLimit.toLocaleString()}
              </span>
            </p>
          </div>
          <div className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">AI credit balance</p>
            <div className="mt-1 flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/Sayvors_Credits.png" alt="" width={26} height={26} className="h-[26px] w-[26px] shrink-0" />
              <p className="text-[18px] font-bold tabular-nums text-ink dark:text-fog">
                {balanceCredits.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                <span className="ml-1 text-[11px] font-semibold text-ink/40 dark:text-fog/40">SC</span>
              </p>
            </div>
            <p className="mt-1 text-[10.5px] text-ink/40 dark:text-fog/40">
              {fmtCents(balance)} · {scPerUsd.toLocaleString()} SC = $1
            </p>
          </div>
          <div className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40 dark:text-fog/40">Plan</p>
            <p className="mt-1 text-[18px] font-bold text-ink dark:text-fog">{currentPlan || "—"}</p>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          {/* messages */}
          <section className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">WhatsApp messages</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
              Added on top of your plan's monthly allowance. The AI stops replying when the limit is reached.
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
                  +{pack.toLocaleString()}
                </button>
              ))}
              <input
                value={messageCustom}
                onChange={(e) => setMessageCustom(e.target.value)}
                inputMode="numeric"
                placeholder="Custom"
                aria-label="Custom message amount"
                className="w-28 rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              />
            </div>
            <button
              type="button"
              onClick={() => void submit("messages", parseCustom(messageCustom) ?? messagePack)}
              disabled={busy !== null}
              className="mt-3 w-full rounded-xl bg-deep-violet px-3 py-2.5 text-[12.5px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
            >
              {busy === "messages" ? "Sending…" : `Request ${(parseCustom(messageCustom) ?? messagePack).toLocaleString()} messages`}
            </button>
          </section>

          {/* AI credit */}
          <section className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">AI credit</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
              Spent on AI replies, analytics and the assistant. Added to the wallet after approval.
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
                  {fmtCents(cents)}
                </button>
              ))}
              <input
                value={creditCustom}
                onChange={(e) => setCreditCustom(e.target.value)}
                inputMode="decimal"
                placeholder="Custom $"
                aria-label="Custom AI credit amount in dollars"
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
                ? "Sending…"
                : `Request ${parseCustom(creditCustom) ? fmtCents(Math.round((parseCustom(creditCustom) ?? 0) * 100)) : fmtCents(creditPack)} credit`}
            </button>
          </section>

          {/* channels */}
          <section className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">Channels</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
              Extra connected numbers, pages or locations beyond your plan.
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
                  +{pack}
                </button>
              ))}
              <input
                value={channelCustom}
                onChange={(e) => setChannelCustom(e.target.value)}
                inputMode="numeric"
                placeholder="Custom"
                aria-label="Custom channel amount"
                className="w-28 rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              />
            </div>
            <button
              type="button"
              onClick={() => void submit("channels", parseCustom(channelCustom) ?? channelPack)}
              disabled={busy !== null}
              className="mt-3 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2.5 text-[12.5px] font-bold text-ink/70 transition hover:border-deep-violet/40 hover:text-deep-violet disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog/70"
            >
              {busy === "channels" ? "Sending…" : `Request ${(parseCustom(channelCustom) ?? channelPack)} channel${(parseCustom(channelCustom) ?? channelPack) === 1 ? "" : "s"}`}
            </button>
          </section>

          {/* enterprise */}
          <section className="rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
            <h2 className="text-[14px] font-bold text-ink dark:text-fog">Enterprise plan</h2>
            <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
              Sales-assisted plan with custom limits, onboarding and support.
              {planSlug === "enterprise" ? " You are already on Enterprise." : ""}
            </p>
            <button
              type="button"
              onClick={() => void submit("plan", null, "enterprise")}
              disabled={busy !== null || planSlug === "enterprise"}
              className="mt-3 w-full rounded-xl border border-ink/[0.1] bg-white px-3 py-2.5 text-[12.5px] font-bold text-ink/70 transition hover:border-deep-violet/40 hover:text-deep-violet disabled:opacity-50 dark:border-fog/[0.12] dark:bg-ink dark:text-fog/70"
            >
              {busy === "plan" ? "Sending…" : planSlug === "enterprise" ? "Current plan" : "Request Enterprise"}
            </button>
          </section>
        </div>

        {/* note + history */}
        <section className="mt-6 rounded-2xl border border-ink/[0.07] bg-white p-4 dark:border-fog/[0.08] dark:bg-ink/60">
          <label className="block text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45 dark:text-fog/45">
            Optional note for the operator
          </label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={500}
            rows={2}
            placeholder="Anything we should know? (optional)"
            className="mt-1.5 w-full resize-none rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12.5px] text-ink outline-none focus:border-deep-violet/40 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
          />
        </section>

        <section className="mt-6">
          <h2 className="text-[13px] font-bold text-ink dark:text-fog">Your requests</h2>
          {requests.isLoading ? (
            <p className="mt-2 text-[12px] text-ink/40 dark:text-fog/40">Loading…</p>
          ) : (requests.data ?? []).length === 0 ? (
            <p className="mt-2 rounded-2xl border border-dashed border-ink/[0.1] p-5 text-center text-[12px] text-ink/45 dark:border-fog/[0.12] dark:text-fog/45">
              No requests yet.
            </p>
          ) : (
            <ul className="mt-2 space-y-2">
              {(requests.data ?? []).map((request) => (
                <li
                  key={request.id}
                  className="flex flex-wrap items-center gap-2 rounded-xl border border-ink/[0.07] bg-white px-3.5 py-2.5 text-[12px] dark:border-fog/[0.08] dark:bg-ink/60"
                >
                  <span className="font-semibold text-ink dark:text-fog">{KIND_LABEL[request.kind] ?? request.kind}</span>
                  <span className="text-ink/55 dark:text-fog/55">{requestSummary(request)}</span>
                  <span className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${statusStyle(request.status)}`}>
                    {request.status}
                  </span>
                  <span className="w-full text-[10.5px] text-ink/40 dark:text-fog/40">
                    {new Date(request.created_at).toLocaleString()}
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
