"use client";

import type { Session } from "@/lib/api-profile";

export default function ProfileSupport({
  sessions,
}: {
  sessions: Session[];
}) {
  return (
    <section aria-label="Security and support" className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm">
      <h3 className="text-[14px] font-bold text-ink">Security & support</h3>
      <p className="mb-4 text-[11px] text-ink/45">Sessions, version, and help in one place.</p>

      <div className="space-y-3">
        <div className="rounded-xl bg-fog/60 px-4 py-3">
          <div className="flex items-center justify-between">
            <p className="text-[12px] font-semibold text-ink">Active sessions</p>
            <span className="rounded-full bg-white px-2 py-0.5 text-[10px] font-bold tabular-nums text-ink/60 ring-1 ring-ink/10">
              {sessions.length}
            </span>
          </div>
          {sessions.length === 0 ? (
            <p className="mt-1 text-[11px] text-ink/45">No other active sessions.</p>
          ) : (
            <ul className="mt-2 max-h-32 space-y-1.5 overflow-y-auto">
              {sessions.slice(0, 5).map((s) => (
                <li key={s.id} className="truncate text-[11px] text-ink/60">
                  {(s.device || "Unknown device").slice(0, 48)}
                  {s.ip ? ` · ${s.ip}` : ""}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between rounded-xl bg-fog/60 px-4 py-3">
          <div>
            <p className="text-[12px] font-semibold text-ink">App version</p>
            <p className="text-[10px] text-ink/40">Latest stable release</p>
          </div>
          <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[10px] font-bold text-emerald-700">
            v2.4.1
          </span>
        </div>

        <div className="flex items-center justify-between rounded-xl bg-fog/60 px-4 py-3">
          <div>
            <p className="text-[12px] font-semibold text-ink">System status</p>
            <p className="text-[10px] text-ink/40">All systems operational</p>
          </div>
          <span className="flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700">
            <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden />
            Operational
          </span>
        </div>
      </div>
    </section>
  );
}
