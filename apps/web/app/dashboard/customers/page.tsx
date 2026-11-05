"use client";

import CustomersTable from "@/components/dashboard/CustomersTable";
import Link from "next/link";

/*
 * The all-contacts page — every person we have ever had contact with,
 * across every channel, in one table. Click a row to open the complete
 * profile in a side panel.
 *
 * The page is thin on purpose: the table owns the data and the panel
 * owns the detail view, the same way the inbox page stays thin and
 * delegates to InboxView.
 */
export default function CustomersPage() {
  return (
    <div className="team-ui flex h-full flex-col gap-3 p-3 sm:gap-4 sm:p-6">
      <div className="flex shrink-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[18px] font-bold text-[var(--ui-ink)] sm:text-[22px]">
            Customers
          </h1>
          <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--ui-ink-2)] sm:text-[13px]">
            <span className="sm:hidden">
              Everyone you have talked to, across every channel.
            </span>
            <span className="hidden sm:inline">
              Every person you have ever had contact with — WhatsApp, Instagram,
              Facebook, Google reviews — in one table. Click a row for the
              complete profile, conversation, and (for Google) the reviews.
            </span>
          </p>
        </div>
        <Link
          href="/dashboard/inbox"
          className="shrink-0 rounded-lg border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[11px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[2px] focus-visible:outline-offset-[-1px] focus-visible:outline-[var(--ui-ink)] sm:text-[12px]"
        >
          Open inbox
        </Link>
      </div>
      <div className="min-h-0 flex-1">
        <CustomersTable />
      </div>
    </div>
  );
}
