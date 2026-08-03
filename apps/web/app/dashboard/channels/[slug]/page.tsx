"use client";

import Breadcrumbs from "@/components/Breadcrumbs";

const channelData: Record<string, { name: string; icon: string; color: string; connected: boolean; fields: string[] }> = {
  instagram: {
    name: "Instagram",
    icon: "📸",
    color: "from-pink-500 to-purple-500",
    connected: true,
    fields: ["Access Token", "Business Account ID", "Webhook Secret"],
  },
  x: {
    name: "X / Twitter",
    icon: "🐦",
    color: "from-sky-400 to-blue-500",
    connected: true,
    fields: ["API Key", "API Secret", "Access Token", "Access Token Secret"],
  },
  facebook: {
    name: "Facebook",
    icon: "👤",
    color: "from-blue-500 to-blue-600",
    connected: false,
    fields: ["App ID", "App Secret", "Page Access Token", "Verify Token"],
  },
  telegram: {
    name: "Telegram",
    icon: "✈️",
    color: "from-blue-400 to-indigo-500",
    connected: true,
    fields: ["Bot Token", "Webhook URL"],
  },
  whatsapp: {
    name: "WhatsApp",
    icon: "💬",
    color: "from-green-400 to-emerald-500",
    connected: true,
    fields: ["Phone Number ID", "Access Token", "Webhook Verify Token"],
  },
  linkedin: {
    name: "LinkedIn",
    icon: "💼",
    color: "from-blue-600 to-blue-700",
    connected: false,
    fields: ["Client ID", "Client Secret", "Access Token"],
  },
};

export default function ChannelAuthPage({ params }: { params: { slug: string } }) {
  const data = channelData[params.slug] || { name: params.slug, icon: "🔗", color: "from-gray-400 to-gray-500", connected: false, fields: [] };

  return (
    <div className="space-y-5">
      <div>
        <Breadcrumbs
          items={[
            { label: "Channels", href: "/dashboard/channels" },
            { label: data.name },
          ]}
        />
        <div className="mt-2 flex items-center gap-3">
          <div className={`flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br ${data.color} text-[20px] text-white`}>
            {data.icon}
          </div>
          <div>
            <h1 className="text-[20px] font-bold text-ink">{data.name}</h1>
            <p className={`text-[12px] font-medium ${data.connected ? "text-emerald-600" : "text-ink/40"}`}>
              {data.connected ? "Connected" : "Not connected"}
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-ink/[0.06] bg-white p-5">
        <h3 className="text-[14px] font-semibold text-ink">
          {data.connected ? "Connection Settings" : "Connect " + data.name}
        </h3>
        <div className="mt-4 space-y-3">
          {data.fields.map((field) => (
            <div key={field} className="space-y-1">
              <label className="text-[12px] font-medium text-ink/60">{field}</label>
              <input
                type="text"
                placeholder={`Enter ${field.toLowerCase()}`}
                className="h-10 w-full rounded-lg border border-ink/[0.08] bg-fog/30 px-3.5 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.06]"
              />
            </div>
          ))}
        </div>
        <div className="mt-5 flex gap-2">
          <button className="flex h-9 items-center justify-center rounded-lg bg-gradient-to-r from-deep-violet to-magenta px-5 text-[13px] font-semibold text-white transition hover:shadow-md active:scale-[0.98]">
            {data.connected ? "Update" : "Connect"}
          </button>
          {data.connected && (
            <button className="flex h-9 items-center justify-center rounded-lg border border-coral/30 px-4 text-[13px] font-medium text-coral transition hover:bg-coral/5 active:scale-[0.98]">
              Disconnect
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
