"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getEntitlements } from "@/lib/api-billing";
import { queryKeys } from "@/lib/query-keys";

/**
 * Monthly WhatsApp message quota banner.
 *
 * The plan allowance is WhatsApp-only; Instagram and other channels are not
 * counted. Shown from 90% usage so the owner has time to act before the AI
 * stops answering. The exhausted state is deliberately explicit: inbound
 * messages still arrive and are stored, but no AI reply is generated until the
 * limit is raised. There is no self-serve top-up yet, so the call to action is
 * the plans page (Enterprise / contact us).
 */
export default function UsageBanner() {
  const { data } = useQuery({
    queryKey: queryKeys.billing.entitlements(),
    queryFn: getEntitlements,
    staleTime: 60_000,
    refetchInterval: 120_000,
    retry: false,
  });

  const limit = data?.max_messages_per_month ?? null;
  if (!data || !limit || limit <= 0) return null;

  const used = data.messages_used_this_month;
  const remaining = Math.max(0, limit - used);
  const ratio = used / limit;
  if (ratio < 0.9) return null;

  const exhausted = remaining === 0;
  const percent = Math.min(100, Math.round(ratio * 100));

  return (
    <div
      role="status"
      className={`flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-4 py-2 text-[11.5px] leading-snug ${
        exhausted
          ? "border-red-200 bg-red-50 text-red-800"
          : "border-amber-200 bg-amber-50 text-amber-800"
      }`}
    >
      <span
        aria-hidden
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white ${
          exhausted ? "bg-red-600" : "bg-amber-500"
        }`}
      >
        !
      </span>
      <span className="min-w-0 flex-1">
        {exhausted ? (
          <>
            <strong className="font-bold">WhatsApp message limit reached.</strong>{" "}
            {used.toLocaleString()} of {limit.toLocaleString()} WhatsApp messages used this
            month. New messages still arrive, but the AI will not reply until the limit
            is raised.
          </>
        ) : (
          <>
            <strong className="font-bold">Running low on WhatsApp messages.</strong>{" "}
            {used.toLocaleString()} of {limit.toLocaleString()} used ({percent}%) —{" "}
            {remaining.toLocaleString()} left this month.
          </>
        )}
      </span>
      <div className="flex shrink-0 items-center gap-2">
        <span className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-black/10 sm:block">
          <span
            className={`block h-full rounded-full ${exhausted ? "bg-red-600" : "bg-amber-500"}`}
            style={{ width: `${percent}%` }}
          />
        </span>
        <Link
          href="/dashboard/plans"
          className={`rounded-full px-2.5 py-1 text-[10.5px] font-bold text-white transition ${
            exhausted ? "bg-red-600 hover:bg-red-700" : "bg-amber-600 hover:bg-amber-700"
          }`}
        >
          Raise limit
        </Link>
      </div>
    </div>
  );
}
