"use client";

import { useState } from "react";
import Link from "next/link";
import LeadsBoard from "@/components/leads/LeadsBoard";
import LeadSettingsPanel from "@/components/leads/LeadSettingsPanel";

/*
 * The all-channels Leads page — WhatsApp, Instagram, and Messenger leads
 * in one board. Reached from the dashboard's Leads glance card; the
 * conversations themselves live in the unified inbox.
 */
export default function LeadsPage() {
  const [showSettings, setShowSettings] = useState(false);

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
        <button
          type="button"
          onClick={() => setShowSettings((v) => !v)}
          aria-expanded={showSettings}
          className="rounded-[8px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 py-1.5 text-[12px] font-semibold text-[var(--ui-ink)] transition hover:bg-[var(--ui-sunken)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-[var(--ui-ink)]"
        >
          {showSettings ? "Hide settings" : "Follow-up & escalation settings"}
        </button>
      </div>

      {showSettings && (
        <section className="mt-4 rounded-[12px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-4 sm:p-5">
          <LeadSettingsPanel />
        </section>
      )}

      <LeadsBoard />
    </div>
  );
}
