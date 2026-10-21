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
    <div className="team-ui h-full overflow-y-auto p-4 sm:p-6">
      <div className="mb-1 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[20px] font-bold text-[var(--ui-ink)] sm:text-[22px]">
            Customers
          </h1>
          <p className="mt-0.5 text-[12px] text-[var(--ui-ink-2)] sm:text-[13px]">
            Every person you have ever had contact with — WhatsApp, Instagram,
            Facebook, Google reviews — in one table. Click a row for the
            complete profile, conversation, and (for Google) the reviews.
          </p>
        </div>
        <Link
          href="/dashboard/inbox"
          className="rounded-[3px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[2px] focus-visible:outline-offset-[-1px] focus-visible:outline-[var(--ui-ink)]"
        >
          Open inbox
        </Link>
      </div>
      <CustomersTable />
    </div>
  );
}
