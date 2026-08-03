"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

const messages = [
  { id: 1, name: "Sarah Chen", avatar: "SC", lastMsg: "Thanks for the quick response!", time: "2m", unread: false },
  { id: 2, name: "Marcus Rivera", avatar: "MR", lastMsg: "Can you send me the invoice?", time: "8m", unread: true },
  { id: 3, name: "Elena Kowalski", avatar: "EK", lastMsg: "The campaign looks great!", time: "15m", unread: false },
  { id: 4, name: "James Okafor", avatar: "JO", lastMsg: "When is the next meeting?", time: "32m", unread: true },
  { id: 5, name: "Aisha Patel", avatar: "AP", lastMsg: "I'll review the proposal today", time: "1h", unread: false },
];

export default function PlatformConversationsPage({ params }: { params: { platform: string } }) {
  const platform = params.platform.charAt(0).toUpperCase() + params.platform.slice(1);

  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs
          items={[
            { label: "Conversations", href: "/dashboard/conversations" },
            { label: platform },
          ]}
        />
        <h1 className="mt-2 text-[20px] font-bold text-ink">{platform} Conversations</h1>
      </div>

      <div className="rounded-xl border border-ink/[0.06] bg-white">
        {messages.map((m) => (
          <a
            key={m.id}
            href={`/dashboard/conversations/${params.platform}/${m.id}`}
            className={`flex items-center gap-3 border-b border-ink/[0.04] px-4 py-3 transition hover:bg-fog/60 ${m.unread ? "bg-deep-violet/[0.02]" : ""}`}
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-deep-violet/10 text-[12px] font-semibold text-deep-violet">
              {m.avatar}
            </div>
            <div className="min-w-0 flex-1">
              <p className={`text-[13px] ${m.unread ? "font-semibold text-ink" : "font-medium text-ink/70"}`}>{m.name}</p>
              <p className="truncate text-[12px] text-ink/40">{m.lastMsg}</p>
            </div>
            <span className="shrink-0 text-[11px] text-ink/30">{m.time}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
