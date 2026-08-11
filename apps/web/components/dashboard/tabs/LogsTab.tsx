"use client";

interface LogsTabProps {
  channelSlug: string;
  channelName: string;
}

const logs = [
  { id: "1", type: "message", action: "Message sent", detail: "Auto-reply to Sarah Chen", time: "2m ago", status: "success" },
  { id: "2", type: "message", action: "Message received", detail: "Inbound from Marcus Rivera", time: "5m ago", status: "success" },
  { id: "3", type: "call", action: "Call completed", detail: "Outbound to Elena Kowalski - 0:45", time: "1h ago", status: "missed" },
  { id: "4", type: "automation", action: "Automation triggered", detail: "Welcome message for new contact", time: "2h ago", status: "success" },
  { id: "5", type: "agent", action: "Agent activated", detail: "Support Bot enabled for this channel", time: "3h ago", status: "success" },
  { id: "6", type: "message", action: "Message sent", detail: "Follow-up to James Okafor", time: "4h ago", status: "success" },
  { id: "7", type: "error", action: "Delivery failed", detail: "Could not deliver to Aisha Patel - rate limit", time: "5h ago", status: "error" },
  { id: "8", type: "connection", action: "Channel connected", detail: "Successfully authenticated with OAuth", time: "1d ago", status: "success" },
];

const typeIcons: Record<string, React.ReactNode> = {
  message: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
    </svg>
  ),
  call: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
    </svg>
  ),
  automation: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
    </svg>
  ),
  agent: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <rect x="3" y="11" width="18" height="10" rx="2" />
      <circle cx="12" cy="5" r="2" />
      <path d="M12 7v4M8 11v4M16 11v4" />
    </svg>
  ),
  error: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <circle cx="12" cy="12" r="10" />
      <line x1="15" y1="9" x2="9" y2="15" />
      <line x1="9" y1="9" x2="15" y2="15" />
    </svg>
  ),
  connection: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
      <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4" />
      <polyline points="10 17 15 12 10 7" />
      <line x1="15" y1="12" x2="3" y2="12" />
    </svg>
  ),
};

const typeColors: Record<string, string> = {
  message: "bg-deep-violet/10 text-deep-violet",
  call: "bg-emerald-100 text-emerald-600",
  automation: "bg-amber-100 text-amber-600",
  agent: "bg-sky-100 text-sky-600",
  error: "bg-coral/10 text-coral",
  connection: "bg-emerald-100 text-emerald-600",
};

export default function LogsTab({ channelSlug, channelName }: LogsTabProps) {
  return (
    <div className="p-4 sm:p-6">
      <div className="mx-auto max-w-3xl space-y-6">
        <section>
          <h2 className="mb-1 text-[15px] font-bold text-ink">Activity Log</h2>
          <p className="mb-4 text-[13px] text-ink/60">All events and activities on {channelName}.</p>

          <div className="space-y-1">
            {logs.map((log, i) => (
              <div
                key={log.id}
                className="flex items-start gap-3 rounded-lg px-3 py-3 transition hover:bg-white/60"
              >
                <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg ${typeColors[log.type]}`}>
                  {typeIcons[log.type]}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[13px] font-semibold text-ink">{log.action}</span>
                    <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${
                      log.status === "success" ? "bg-emerald-100 text-emerald-700" :
                      log.status === "error" ? "bg-coral/10 text-coral" :
                      "bg-amber-100 text-amber-700"
                    }`}>
                      {log.status}
                    </span>
                  </div>
                  <p className="text-[11px] text-ink/50">{log.detail}</p>
                </div>

                <span className="text-[10px] text-ink/35 shrink-0">{log.time}</span>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-1 text-[15px] font-bold text-ink">Log Settings</h2>
          <p className="mb-4 text-[13px] text-ink/60">Configure logging and retention.</p>
          <div className="rounded-xl border-2 border-white bg-white/80 p-4 sm:p-5 space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-semibold text-ink">Log Retention</p>
                <p className="text-[11px] text-ink/50">How long to keep activity logs</p>
              </div>
              <span className="rounded-xl bg-ink/[0.04] px-3 py-1.5 text-[12px] font-semibold text-ink/60">30 days</span>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[13px] font-semibold text-ink">Export Logs</p>
                <p className="text-[11px] text-ink/50">Download logs as CSV</p>
              </div>
              <button className="rounded-lg border-2 border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/60 transition hover:bg-ink/[0.03]">
                Export
              </button>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
