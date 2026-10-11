"use client";

import Link from "next/link";
import LeadsBoard from "@/components/leads/LeadsBoard";

/*
 * Instagram hub's Leads tab: the shared all-channels LeadsBoard pinned to
 * this account's DMs (server-side platform filter, no channel chips).
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";
const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";

export default function LeadsTab() {
  return (
    <section className={PANEL}>
      <div>
        <h3 className={`text-[15px] font-semibold ${INK}`}>Leads</h3>
        <p className={`mt-1 text-[12px] ${INK2}`}>
          Spotted by the AI in your DMs. The full conversations live in the{" "}
          <Link href="/dashboard/channels/inbox" className="underline underline-offset-2">
            inbox
          </Link>
          .
        </p>
      </div>
      <LeadsBoard platform="instagram" />
    </section>
  );
}
