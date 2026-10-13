"use client";

import Link from "next/link";
import LeadsBoard from "@/components/leads/LeadsBoard";

/*
 * The all-channels Leads page — WhatsApp, Instagram, and Messenger leads
 * in one board. Reached from the dashboard's Leads glance card; the
 * conversations themselves live in the unified inbox.
 *
 * Follow-up and escalation settings live on /dashboard/settings — they are
 * account-wide rules an owner sets once, not per-conversation data.
 */
export default function LeadsPage() {
  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <div className="mb-1 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">Leads</h1>
          <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">
            Every conversation the AI turned into a lead — captured with what
            they need, their requirements, and their contact details. The
            conversations live in the{" "}
            <Link href="/dashboard/channels/inbox" className="underline underline-offset-2">
              inbox
            </Link>
            .
          </p>
        </div>
        <Link
          href="/dashboard/settings"
          className="rounded-[3px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[2px] focus-visible:outline-offset-[-1px] focus-visible:outline-[var(--ui-ink)]"
        >
          Follow-up &amp; escalation settings
        </Link>
      </div>
      <LeadsBoard />
    </div>
  );
}
