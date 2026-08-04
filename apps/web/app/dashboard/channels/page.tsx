"use client";

import Breadcrumbs from "@/components/Breadcrumbs";
import Link from "next/link";

const channels = [
  { name: "Instagram", icon: "📸", status: "connected", conversations: 124, color: "from-pink-500 to-purple-500", slug: "instagram" },
  { name: "X / Twitter", icon: "🐦", status: "connected", conversations: 67, color: "from-sky-400 to-blue-500", slug: "x" },
  { name: "Facebook", icon: "👤", status: "disconnected", conversations: 0, color: "from-blue-500 to-blue-600", slug: "facebook" },
  { name: "Telegram", icon: "✈️", status: "connected", conversations: 45, color: "from-blue-400 to-indigo-500", slug: "telegram" },
  { name: "WhatsApp", icon: "💬", status: "connected", conversations: 89, color: "from-green-400 to-emerald-500", slug: "whatsapp" },
  { name: "LinkedIn", icon: "💼", status: "disconnected", conversations: 0, color: "from-blue-600 to-blue-700", slug: "linkedin" },
];

export default function ChannelsPage() {
  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Channels" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink dark:text-fog">Channels</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Connect and manage your messaging platforms.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {channels.map((c) => (
          <Link
            key={c.name}
            href={`/dashboard/channels/${c.slug}`}
            className="group flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 transition hover:border-deep-violet/20 hover:shadow-sm dark:border-fog/[0.06] dark:bg-ink dark:hover:border-deep-violet/20"
          >
            <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${c.color} text-[22px] text-white shadow-sm`}>
              {c.icon}
            </div>
            <div className="flex-1">
              <p className="text-[14px] font-semibold text-ink group-hover:text-deep-violet dark:text-fog">{c.name}</p>
              <p className="text-[12px] text-ink/40 dark:text-fog/40">{c.conversations} conversations</p>
            </div>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
              c.status === "connected" ? "bg-emerald-50 text-emerald-600" : "bg-ink/[0.04] text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40"
            }`}>{c.status}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
