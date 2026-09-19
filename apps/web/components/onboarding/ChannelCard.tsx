interface ChannelCardProps {
  name: string;
  slug: string;
  icon: string;
  color: string;
  soon?: boolean;
  connected: boolean;
  onConnect?: () => void;
}

export default function ChannelCard({ name, icon, color, soon = false, connected, onConnect }: ChannelCardProps) {
  return (
    <div className="flex items-center gap-4 rounded-xl border border-ink/[0.06] bg-white p-5 transition hover:border-deep-violet/20 hover:shadow-sm dark:border-fog/[0.06] dark:bg-ink dark:hover:border-deep-violet/20">
      <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${color} text-[22px] text-white shadow-sm`}>
        {icon}
      </div>
      <div className="flex-1">
        <p className="text-[14px] font-semibold text-ink dark:text-fog">{name}</p>
        <p className="text-[12px] text-ink/40 dark:text-fog/40">
          {connected ? "Connected" : soon ? "Coming soon" : "Not connected yet"}
        </p>
      </div>
      {connected ? (
        <span className="rounded-full bg-emerald-50 px-3 py-1 text-[11px] font-semibold text-emerald-600 dark:bg-emerald-900/20 dark:text-emerald-400">
          Connected
        </span>
      ) : soon ? (
        <span className="rounded-full bg-ink/[0.04] px-3 py-1 text-[11px] font-semibold text-ink/40 dark:bg-fog/[0.06] dark:text-fog/40">
          Soon
        </span>
      ) : (
        <button
          onClick={onConnect}
          className="rounded-full bg-deep-violet px-4 py-1.5 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
        >
          Connect
        </button>
      )}
    </div>
  );
}
