"use client";

export default function ProfileSupport() {
  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-5">
      <h2 className="text-[14px] font-bold text-ink mb-4">Support & Version</h2>

      <div className="space-y-3">
        {/* Version */}
        <div className="flex items-center justify-between rounded-xl bg-ink/[0.03] px-4 py-3">
          <div>
            <p className="text-[12px] font-semibold text-ink">App Version</p>
            <p className="text-[10px] text-ink/40">Latest stable release</p>
          </div>
          <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-[10px] font-bold text-emerald-600">v2.4.1</span>
        </div>

        {/* Support team */}
        <div className="flex items-center justify-between rounded-xl bg-ink/[0.03] px-4 py-3">
          <div>
            <p className="text-[12px] font-semibold text-ink">Support Team</p>
            <p className="text-[10px] text-ink/40">Available 24/7 for Pro users</p>
          </div>
          <button className="rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-bold text-white transition hover:bg-deep-violet/90">
            Contact
          </button>
        </div>

        {/* Documentation */}
        <div className="flex items-center justify-between rounded-xl bg-ink/[0.03] px-4 py-3">
          <div>
            <p className="text-[12px] font-semibold text-ink">Documentation</p>
            <p className="text-[10px] text-ink/40">Guides, tutorials, and API docs</p>
          </div>
          <button className="rounded-lg border-2 border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/50 transition hover:border-deep-violet/30 hover:text-deep-violet">
            Open
          </button>
        </div>

        {/* Status */}
        <div className="flex items-center justify-between rounded-xl bg-ink/[0.03] px-4 py-3">
          <div>
            <p className="text-[12px] font-semibold text-ink">System Status</p>
            <p className="text-[10px] text-ink/40">All systems operational</p>
          </div>
          <span className="flex items-center gap-1.5 text-[10px] font-semibold text-emerald-600">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Operational
          </span>
        </div>
      </div>
    </div>
  );
}
