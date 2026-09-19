"use client";

import { useState } from "react";
import type { Conversation } from "@/lib/channel-data";

interface ChatListProps {
  conversations: Conversation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function ChatList({ conversations, selectedId, onSelect }: ChatListProps) {
  const [search, setSearch] = useState("");

  const filtered = conversations.filter((c) =>
    c.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="flex h-full flex-col border-r border-ink/[0.06] bg-white dark:border-fog/[0.06] dark:bg-ink">
      {/* Search */}
      <div className="border-b border-ink/[0.04] p-3 dark:border-fog/[0.04]">
        <div className="relative">
          <svg
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink/25 dark:text-fog/25"
          >
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            type="text"
            placeholder="Search conversations..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 w-full rounded-md border border-ink/[0.08] bg-fog/40 pl-8 pr-3 text-[12px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.06] dark:border-fog/[0.08] dark:bg-ink/40 dark:text-fog dark:placeholder:text-fog/30 dark:focus:bg-ink"
          />
        </div>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-ink/[0.04] dark:bg-fog/[0.04]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 text-ink/20 dark:text-fog/20">
                <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
              </svg>
            </div>
            <p className="mt-3 text-[12px] text-ink/40 dark:text-fog/40">No conversations found</p>
          </div>
        ) : (
          filtered.map((conv) => (
            <button
              key={conv.id}
              onClick={() => onSelect(conv.id)}
              className={`flex w-full items-center gap-3 border-b border-ink/[0.04] px-4 py-3 text-left transition hover:bg-fog/60 dark:border-fog/[0.04] dark:hover:bg-fog/[0.04] ${
                selectedId === conv.id ? "bg-deep-violet/[0.04]" : ""
              } ${conv.unread ? "bg-deep-violet/[0.02]" : ""}`}
            >
              {/* Avatar */}
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-deep-violet/10 text-[12px] font-semibold text-deep-violet">
                {conv.avatar}
              </div>

              {/* Content */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between">
                  <span className={`text-[13px] ${conv.unread ? "font-semibold text-ink dark:text-fog" : "font-medium text-ink/70 dark:text-fog/70"}`}>
                    {conv.name}
                  </span>
                  <span className="shrink-0 text-[10px] text-ink/30 dark:text-fog/30">{conv.time}</span>
                </div>
                <div className="flex items-center justify-between">
                  <p className="truncate text-[11px] text-ink/40 dark:text-fog/40">{conv.lastMsg}</p>
                  {conv.unread && (
                    <span className="ml-2 h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet" />
                  )}
                </div>
              </div>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
