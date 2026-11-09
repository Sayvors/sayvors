"use client";

import Link from "next/link";
import LeadsBoard from "@/components/leads/LeadsBoard";
import { useI18n } from "@/lib/i18n/I18nProvider";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, value]) => out.replaceAll(`{${key}}`, String(value)),
    s,
  );
}

/*
 * The all-channels Leads page — WhatsApp, Instagram, and Messenger leads
 * in one board. Reached from the dashboard's Leads glance card; the
 * conversations themselves live in the unified inbox.
 *
 * Follow-up and escalation settings live on /dashboard/settings — they are
 * account-wide rules an owner sets once, not per-conversation data.
 */
export default function LeadsPage() {
  const { t } = useI18n();
  const b = t.reviews.board;
  return (
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <div className="mb-1 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">{b.pageTitle}</h1>
          <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">
            {b.pageBefore}
            <Link href="/dashboard/channels/inbox" className="underline underline-offset-2">
              {b.pageInbox}
            </Link>
            {b.pageAfter}
          </p>
        </div>
        <Link
          href="/dashboard/settings"
          className="rounded-[3px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[2px] focus-visible:outline-offset-[-1px] focus-visible:outline-[var(--ui-ink)]"
        >
          {b.settingsLink}
        </Link>
      </div>
      <LeadsBoard />
    </div>
  );
}
