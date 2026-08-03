"use client";

import Breadcrumbs from "@/components/Breadcrumbs";
import Link from "next/link";

const platforms = [
  { name: "Instagram", icon: "📸", conversations: 124, unread: 8, color: "from-pink-500 to-purple-500" },
  { name: "WhatsApp", icon: "💬", conversations: 89, unread: 3, color: "from-green-400 to-emerald-500" },
  { name: "X / Twitter", icon: "🐦", conversations: 67, unread: 0, color: "from-sky-400 to-blue-500" },
  { name: "Telegram", icon: "✈️", conversations: 45, unread: 2, color: "from-blue-400 to-indigo-500" },
  { name: "Facebook", icon: "👤", conversations: 34, unread: 1, color: "from-blue-500 to-blue-600" },
  { name: "LinkedIn", icon: "💼", conversations: 23, unread: 0, color: "from-blue-600 to-blue-700" },
];

export default function ConversationsPage() {
  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs items={[{ label: "Conversations" }]} />
        <h1 className="mt-2 text-[20px] font-bold text-ink">Conversations</h1>
        <p className="mt-0.5 text-[13px] text-ink/45">Select a platform to view conversations.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {platforms.map((p) => (
          <Link
            key={p.name}
            href={`/dashboard/conversations/${p.name.toLowerCase().replace(/ \/ /g, "-").replace(" ", "")}`}
            className="group flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 transition hover:border-deep-violet/20 hover:shadow-sm"
          >
            <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${p.color} text-[22px] text-white shadow-sm`}>
              {p.icon}
            </div>
            <div className="flex-1">
              <p className="text-[14px] font-semibold text-ink group-hover:text-deep-violet">{p.name}</p>
              <p className="text-[12px] text-ink/40">{p.conversations} conversations</p>
            </div>
            {p.unread > 0 && (
              <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-coral px-1.5 text-[10px] font-semibold text-white">
                {p.unread}
              </span>
            )}
          </Link>
        ))}
      </div>
    </div>
  );
}
