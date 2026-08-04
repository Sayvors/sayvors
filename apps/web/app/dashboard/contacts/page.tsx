"use client";

import Breadcrumbs from "@/components/Breadcrumbs";
import Link from "next/link";

const contacts = [
  { id: 1, name: "Sarah Chen", email: "sarah@example.com", source: "Instagram", score: 92, status: "hot", value: "$2,400" },
  { id: 2, name: "Marcus Rivera", email: "marcus@example.com", source: "WhatsApp", score: 85, status: "hot", value: "$1,800" },
  { id: 3, name: "Elena Kowalski", email: "elena@example.com", source: "X", score: 78, status: "warm", value: "$950" },
  { id: 4, name: "James Okafor", email: "james@example.com", source: "Telegram", score: 65, status: "warm", value: "$3,200" },
  { id: 5, name: "Aisha Patel", email: "aisha@example.com", source: "Facebook", score: 90, status: "hot", value: "$4,100" },
  { id: 6, name: "David Kim", email: "david@example.com", source: "LinkedIn", score: 45, status: "cold", value: "$600" },
];

export default function ContactsPage() {
  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Contacts" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Contacts</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">All your leads and contacts in one place.</p>
      </div>

      <div className="overflow-hidden rounded-xl border border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-ink/[0.06] bg-ink/[0.02] dark:border-fog/[0.06] dark:bg-fog/[0.02]">
              <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/40 dark:text-fog/40">Name</th>
              <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/40 dark:text-fog/40">Email</th>
              <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/40 dark:text-fog/40">Source</th>
              <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/40 dark:text-fog/40">Score</th>
              <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/40 dark:text-fog/40">Status</th>
              <th className="px-4 py-3 text-[11px] font-semibold uppercase tracking-wider text-ink/40 dark:text-fog/40">Value</th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => (
              <tr key={c.id} className="border-b border-ink/[0.03] last:border-0 hover:bg-fog/40 dark:border-fog/[0.03] dark:hover:bg-fog/[0.04]">
                <td className="px-4 py-3">
                  <Link href={`/dashboard/contacts/${c.id}`} className="text-[13px] font-medium text-ink hover:text-deep-violet dark:text-fog dark:hover:text-deep-violet">{c.name}</Link>
                </td>
                <td className="px-4 py-3 text-[12px] text-ink/50 dark:text-fog/50">{c.email}</td>
                <td className="px-4 py-3">
                  <span className="rounded bg-ink/[0.04] px-2 py-0.5 text-[10px] font-medium text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40">{c.source}</span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1.5">
                    <div className="h-1.5 w-12 overflow-hidden rounded-full bg-ink/[0.04] dark:bg-fog/[0.04]">
                      <div className={`h-full rounded-full ${c.score >= 80 ? "bg-emerald-500" : c.score >= 60 ? "bg-amber-400" : "bg-coral"}`} style={{ width: `${c.score}%` }} />
                    </div>
                    <span className="text-[11px] text-ink/40 dark:text-fog/40">{c.score}</span>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                    c.status === "hot" ? "bg-coral/10 text-coral" :
                    c.status === "warm" ? "bg-amber-50 text-amber-600" :
                    "bg-ink/[0.04] text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40"
                  }`}>{c.status}</span>
                </td>
                <td className="px-4 py-3 text-[13px] font-semibold text-ink dark:text-fog">{c.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
