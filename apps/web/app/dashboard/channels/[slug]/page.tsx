"use client";

import Breadcrumbs from "@/components/Breadcrumbs";
import { use } from "react";

const channelData: Record<string, { name: string; icon: string; color: string; connected: boolean; provider: string; scopes: string[] }> = {
  instagram: {
    name: "Instagram",
    icon: "📸",
    color: "from-pink-500 to-purple-500",
    connected: true,
    provider: "instagram",
    scopes: ["instagram_basic", "instagram_manage_messages", "pages_show_list"],
  },
  x: {
    name: "X / Twitter",
    icon: "🐦",
    color: "from-sky-400 to-blue-500",
    connected: true,
    provider: "twitter",
    scopes: ["tweet.read", "users.read", "dm.read", "dm.write"],
  },
  facebook: {
    name: "Facebook",
    icon: "👤",
    color: "from-blue-500 to-blue-600",
    connected: false,
    provider: "facebook",
    scopes: ["pages_manage_metadata", "pages_messaging", "pages_show_list"],
  },
  telegram: {
    name: "Telegram",
    icon: "✈️",
    color: "from-blue-400 to-indigo-500",
    connected: true,
    provider: "telegram",
    scopes: ["bot_token"],
  },
  whatsapp: {
    name: "WhatsApp",
    icon: "💬",
    color: "from-green-400 to-emerald-500",
    connected: true,
    provider: "whatsapp",
    scopes: ["whatsapp_business_messaging", "whatsapp_business_management"],
  },
  linkedin: {
    name: "LinkedIn",
    icon: "💼",
    color: "from-blue-600 to-blue-700",
    connected: false,
    provider: "linkedin",
    scopes: ["r_liteprofile", "r_emailaddress", "w_member_social"],
  },
};

export default function ChannelAuthPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = use(params);
  const data = channelData[slug] || { name: slug, icon: "🔗", color: "from-gray-400 to-gray-500", connected: false, provider: slug, scopes: [] };

  const handleOAuth = () => {
    // TODO: Wire to backend OAuth endpoint
    // window.location.href = `${API_URL}/auth/oauth/${data.provider}`;
    alert(`OAuth flow for ${data.name} will connect to backend`);
  };

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
            <h1 className="text-[20px] font-bold text-ink dark:text-fog">{data.name}</h1>
            <p className={`text-[12px] font-medium ${data.connected ? "text-emerald-600" : "text-ink/40 dark:text-fog/40"}`}>
              {data.connected ? "Connected" : "Not connected"}
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
        <h3 className="text-[14px] font-semibold text-ink dark:text-fog">
          {data.connected ? "Connection Settings" : "Connect " + data.name}
        </h3>

        {data.connected ? (
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-3 rounded-lg bg-emerald-50 px-4 py-3 dark:bg-emerald-900/20">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5 text-emerald-600">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <div>
                <p className="text-[13px] font-medium text-emerald-700">Connected via OAuth</p>
                <p className="text-[11px] text-emerald-600/70">Last synced: 2 minutes ago</p>
              </div>
            </div>
            <div className="space-y-2">
              <p className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Permissions granted:</p>
              <div className="flex flex-wrap gap-1.5">
                {data.scopes.map((scope) => (
                  <span key={scope} className="rounded-md bg-deep-violet/[0.06] px-2 py-1 text-[10px] font-medium text-deep-violet dark:bg-deep-violet/20">
                    {scope}
                  </span>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-4">
            <p className="text-[13px] text-ink/50 dark:text-fog/50 mb-4">
              Click the button below to authorize Sayvors to access your {data.name} account. You&apos;ll be redirected to {data.name} to grant permissions.
            </p>
            <div className="space-y-2 mb-4">
              <p className="text-[12px] font-medium text-ink/60 dark:text-fog/60">Required permissions:</p>
              <div className="flex flex-wrap gap-1.5">
                {data.scopes.map((scope) => (
                  <span key={scope} className="rounded-md bg-ink/[0.04] px-2 py-1 text-[10px] font-medium text-ink/60 dark:bg-fog/[0.04] dark:text-fog/60">
                    {scope}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="mt-5 flex gap-2">
          {data.connected ? (
            <>
              <button
                onClick={handleOAuth}
                className="flex h-9 items-center justify-center rounded-lg border border-ink/[0.08] px-4 text-[13px] font-medium text-ink transition hover:bg-ink/[0.04] dark:border-fog/[0.08] dark:text-fog dark:hover:bg-fog/[0.04]"
              >
                Re-authorize
              </button>
              <button className="flex h-9 items-center justify-center rounded-lg border border-coral/30 px-4 text-[13px] font-medium text-coral transition hover:bg-coral/5 active:scale-[0.98]">
                Disconnect
              </button>
            </>
          ) : (
            <button
              onClick={handleOAuth}
              className="flex h-10 items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-deep-violet to-magenta px-6 text-[13px] font-semibold text-white transition hover:shadow-md active:scale-[0.98]"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
                <polyline points="10 17 15 12 10 7" />
                <line x1="15" y1="12" x2="3" y2="12" />
              </svg>
              Connect with {data.name}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
