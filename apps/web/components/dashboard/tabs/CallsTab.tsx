"use client";

interface CallsTabProps {
  channelSlug: string;
  channelName: string;
}

const recentCalls = [
  { id: "1", name: "Sarah Chen", type: "outbound", duration: "4:32", time: "2m ago", status: "completed", outcome: "Interested" },
  { id: "2", name: "Marcus Rivera", type: "inbound", duration: "2:15", time: "18m ago", status: "completed", outcome: "Follow-up" },
  { id: "3", name: "Elena Kowalski", type: "outbound", duration: "0:45", time: "1h ago", status: "missed", outcome: "No answer" },
  { id: "4", name: "James Okafor", type: "outbound", duration: "6:10", time: "2h ago", status: "completed", outcome: "Converted" },
  { id: "5", name: "Aisha Patel", type: "inbound", duration: "3:22", time: "3h ago", status: "completed", outcome: "Support" },
];

export default function CallsTab({ channelSlug, channelName }: CallsTabProps) {
  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <section>
          <h2 className="mb-1 text-[15px] font-bold text-ink">Recent Calls</h2>
          <p className="mb-4 text-[13px] text-ink/60">Inbound and outbound calls on {channelName}.</p>

          <div className="space-y-2">
            {recentCalls.map((call) => (
              <div
                key={call.id}
                className="flex items-center gap-3 rounded-xl border-2 border-white bg-white/80 p-3 sm:p-4 transition hover:bg-white"
              >
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${
                  call.type === "outbound" ? "bg-deep-violet/10 text-deep-violet" : "bg-emerald-100 text-emerald-600"
                }`}>
                  {call.type === "outbound" ? (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
                      <polyline points="17 1 21 5 17 9" />
                    </svg>
                  ) : (
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
                      <polyline points="7 1 3 5 7 9" />
                    </svg>
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold text-ink">{call.name}</span>
                    <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${
                      call.type === "outbound" ? "bg-deep-violet/10 text-deep-violet" : "bg-emerald-100 text-emerald-700"
                    }`}>
                      {call.type === "outbound" ? "OUT" : "IN"}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-ink/50">
                    <span>{call.duration}</span>
                    <span>&middot;</span>
                    <span>{call.time}</span>
                  </div>
                </div>

                <div className="text-right">
                  <span className={`text-[11px] font-semibold ${
                    call.status === "completed" ? "text-emerald-600" : "text-coral"
                  }`}>
                    {call.outcome}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-1 text-[15px] font-bold text-ink">Call Settings</h2>
          <p className="mb-4 text-[13px] text-ink/60">Configure call behavior for this channel.</p>
          <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-semibold text-ink">Auto-Answer Calls</p>
                <p className="text-[11px] text-ink/50">Automatically answer incoming calls</p>
              </div>
              <div className="h-5 w-9 rounded-full bg-deep-violet p-0.5 transition">
                <div className="h-4 w-4 rounded-full bg-white shadow-sm translate-x-4" />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-semibold text-ink">Call Recording</p>
                <p className="text-[11px] text-ink/50">Record calls for quality and compliance</p>
              </div>
              <div className="h-5 w-9 rounded-full bg-deep-violet p-0.5 transition">
                <div className="h-4 w-4 rounded-full bg-white shadow-sm translate-x-4" />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-semibold text-ink">AI Voice Agent</p>
                <p className="text-[11px] text-ink/50">Use AI to handle calls automatically</p>
              </div>
              <div className="h-5 w-9 rounded-full bg-ink/10 p-0.5 transition">
                <div className="h-4 w-4 rounded-full bg-white shadow-sm" />
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
