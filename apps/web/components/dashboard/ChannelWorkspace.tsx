"use client";

import { useState } from "react";
import ChannelHeader, { type ChannelTab } from "./ChannelHeader";
import ChatList from "./ChatList";
import ChatView from "./ChatView";
import AnalyticsTab from "./tabs/AnalyticsTab";
import ProfileTab from "./tabs/ProfileTab";
import AdsTab from "./tabs/AdsTab";
import LeadsTab from "./tabs/LeadsTab";
import CallsTab from "./tabs/CallsTab";
import LogsTab from "./tabs/LogsTab";
import {
  channels as initialChannels,
  conversationsByChannel,
  messagesByConversation,
  type Channel,
  type Conversation,
} from "@/lib/channel-data";

interface ChannelWorkspaceProps {
  slug: string;
}

export default function ChannelWorkspace({ slug }: ChannelWorkspaceProps) {
  const [channelData, setChannelData] = useState<Channel[]>(initialChannels);
  const [selectedConvId, setSelectedConvId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Record<string, Conversation[]>>(conversationsByChannel);
  const [activeTab, setActiveTab] = useState<ChannelTab>("inbox");

  const channel = channelData.find((c) => c.slug === slug);
  const channelConversations = conversations[slug] || [];
  const selectedConversation = channelConversations.find((c) => c.id === selectedConvId);
  const selectedMessages = selectedConvId ? messagesByConversation[selectedConvId] || [] : [];

  const handleToggleAgent = (convId: string) => {
    setConversations((prev) => ({
      ...prev,
      [slug]: (prev[slug] || []).map((c) =>
        c.id === convId ? { ...c, agentMode: !c.agentMode } : c
      ),
    }));
  };

  const handleConnect = () => {
    setChannelData((prev) =>
      prev.map((c) => (c.slug === slug ? { ...c, connected: true } : c))
    );
  };

  if (!channel) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-[13px] text-ink/60">Channel not found</p>
      </div>
    );
  }

  // State A: Not connected
  if (!channel.connected) {
    return (
      <div className="flex h-full flex-col">
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mx-auto max-w-md">
            <div className="rounded-2xl border-2 border-white bg-white/80 p-6">
              <div className="flex flex-col items-center text-center">
                <div className={`flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br ${channel.color} text-[32px] text-white shadow-lg`}>
                  {channel.icon}
                </div>
                <h2 className="mt-4 text-[18px] font-bold text-ink">Connect {channel.name}</h2>
                <p className="mt-2 text-[13px] text-ink/60">
                  Authorize Sayvors to access your {channel.name} account. You&apos;ll be redirected to {channel.name} to grant permissions.
                </p>
              </div>

              {/* Permissions */}
              <div className="mt-6">
                <p className="text-[12px] font-semibold text-ink/60 mb-2">Required permissions:</p>
                <div className="flex flex-wrap gap-1.5">
                  {channel.scopes.map((scope) => (
                    <span
                      key={scope}
                      className="rounded-lg bg-deep-violet/[0.06] px-2.5 py-1 text-[10px] font-semibold text-deep-violet/70"
                    >
                      {scope}
                    </span>
                  ))}
                </div>
              </div>

              {/* Connect button */}
              <button
                onClick={handleConnect}
                className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-deep-violet px-6 py-3 text-[13px] font-bold text-white shadow-lg shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-[0.98]"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                  <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
                  <polyline points="10 17 15 12 10 7" />
                  <line x1="15" y1="12" x2="3" y2="12" />
                </svg>
                Connect with {channel.name}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Connected — render based on active tab
  return (
    <div className="flex h-full flex-col bg-[#f3f0ff]">
      {/* Header with tabs */}
      <ChannelHeader
        channelName={channel.name}
        channelSlug={slug}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />

      {/* Tab content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === "inbox" && (
          <div className="flex h-full">
            {/* Chat list panel */}
            <div className={`${selectedConversation ? "hidden md:flex" : "flex"} w-full flex-col md:w-80 md:min-w-[320px]`}>
              <ChatList
                conversations={channelConversations}
                selectedId={selectedConvId}
                onSelect={setSelectedConvId}
              />
            </div>

            {/* Chat view panel */}
            {selectedConversation ? (
              <div className="flex flex-1 flex-col">
                <ChatView
                  conversation={selectedConversation}
                  messages={selectedMessages}
                  onToggleAgent={handleToggleAgent}
                />
              </div>
            ) : (
              <div className="hidden flex-1 flex-col items-center justify-center bg-white/40 md:flex">
                <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-deep-violet/[0.06]">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-8 w-8 text-deep-violet/30">
                    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
                  </svg>
                </div>
                <p className="mt-4 text-[13px] font-semibold text-ink/40">Select a conversation</p>
                <p className="mt-1 text-[11px] text-ink/30">Choose a chat from the list to start messaging</p>
              </div>
            )}
          </div>
        )}

        {activeTab === "analytics" && (
          <div className="h-full overflow-y-auto">
            <AnalyticsTab channelSlug={slug} channelName={channel.name} />
          </div>
        )}

        {activeTab === "profile" && (
          <div className="h-full overflow-y-auto">
            <ProfileTab channelSlug={slug} channelName={channel.name} />
          </div>
        )}

        {activeTab === "ads" && (
          <div className="h-full overflow-y-auto">
            <AdsTab channelSlug={slug} channelName={channel.name} />
          </div>
        )}

        {activeTab === "leads" && (
          <div className="h-full overflow-y-auto">
            <LeadsTab channelSlug={slug} channelName={channel.name} />
          </div>
        )}

        {activeTab === "calls" && (
          <div className="h-full overflow-y-auto">
            <CallsTab channelSlug={slug} channelName={channel.name} />
          </div>
        )}

        {activeTab === "logs" && (
          <div className="h-full overflow-y-auto">
            <LogsTab channelSlug={slug} channelName={channel.name} />
          </div>
        )}
      </div>
    </div>
  );
}
