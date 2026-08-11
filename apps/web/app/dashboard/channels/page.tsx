"use client";

import Link from "next/link";
import { channels } from "@/lib/channel-data";

export default function ChannelsPage() {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-5">
      <div>
        <h1 className="text-[20px] font-bold text-ink dark:text-fog">Channels</h1>
        <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">Select a channel from the sidebar to get started.</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {channels.map((c) => (
          <Link
            key={c.slug}
            href={`/dashboard/channels/${c.slug}`}
            className="group flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-4 transition hover:border-deep-violet/20 hover:shadow-sm dark:border-fog/[0.06] dark:bg-ink dark:hover:border-deep-violet/20"
          >
            <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${c.color} text-[22px] text-white shadow-sm`}>
              {c.icon}
            </div>
            <div className="flex-1">
              <p className="text-[14px] font-semibold text-ink group-hover:text-deep-violet dark:text-fog">{c.name}</p>
              <p className="text-[12px] text-ink/40 dark:text-fog/40">
                {c.connected ? "Connected" : "Not connected"}
              </p>
            </div>
            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
              c.connected ? "bg-emerald-50 text-emerald-600" : "bg-ink/[0.04] text-ink/40 dark:bg-fog/[0.04] dark:text-fog/40"
            }`}>
              {c.connected ? "connected" : "disconnected"}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
