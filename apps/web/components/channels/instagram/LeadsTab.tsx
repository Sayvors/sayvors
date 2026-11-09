"use client";

import Link from "next/link";
import LeadsBoard from "@/components/leads/LeadsBoard";
import { useI18n } from "@/lib/i18n/I18nProvider";

/*
 * Instagram hub's Leads tab: the shared all-channels LeadsBoard pinned to
 * this account's DMs (server-side platform filter, no channel chips).
 */

const INK = "text-[var(--ui-ink)]";
const INK2 = "text-[var(--ui-ink-2)]";
const PANEL = "ui-panel bg-[var(--ui-surface)] p-6";

export default function LeadsTab() {
  const { t } = useI18n();
  const l = t.channelHub.instagram.leads;
  return (
    <section className={PANEL}>
      <div>
        <h3 className={`text-[15px] font-semibold ${INK}`}>{l.title}</h3>
        <p className={`mt-1 text-[12px] ${INK2}`}>
          {l.before}
          <Link href="/dashboard/channels/inbox" className="underline underline-offset-2">
            {l.inbox}
          </Link>
          {l.after}
        </p>
      </div>
      <LeadsBoard platform="instagram" />
    </section>
  );
}
