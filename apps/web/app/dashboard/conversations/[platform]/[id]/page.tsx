"use client";

import Breadcrumbs from "@/components/Breadcrumbs";
import { useState } from "react";

const dummyMessages = [
  { id: 1, role: "user" as const, content: "Hi, I'm interested in your product. Can you tell me more about pricing?", time: "10:32 AM" },
  { id: 2, role: "agent" as const, content: "Hello Sarah! I'd be happy to help. We have three plans: Starter ($29/mo), Pro ($79/mo), and Enterprise (custom). Which fits your needs?", time: "10:33 AM" },
  { id: 3, role: "user" as const, content: "The Pro plan looks good. Does it include API access?", time: "10:35 AM" },
  { id: 4, role: "agent" as const, content: "Yes, the Pro plan includes full API access, up to 10,000 requests/month, priority support, and all AI features.", time: "10:35 AM" },
  { id: 5, role: "user" as const, content: "Great, I'll sign up for the Pro plan.", time: "10:37 AM" },
];

export default function SpecificConversationPage({ params }: { params: { platform: string; id: string } }) {
  const [input, setInput] = useState("");
  const platform = params.platform.charAt(0).toUpperCase() + params.platform.slice(1);

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col">
      <div className="mb-4">
        <Breadcrumbs
          items={[
            { label: "Conversations", href: "/dashboard/conversations" },
            { label: platform, href: `/dashboard/conversations/${params.platform}` },
            { label: `Chat #${params.id}` },
          ]}
        />
        <h1 className="mt-2 text-[18px] font-bold text-ink">Sarah Chen</h1>
        <p className="text-[12px] text-ink/40">{platform} · Active now</p>
      </div>

      <div className="flex-1 overflow-y-auto rounded-xl border border-ink/[0.06] bg-white p-4">
        <div className="space-y-4">
          {dummyMessages.map((m) => (
            <div key={m.id} className={`flex ${m.role === "user" ? "justify-start" : "justify-end"}`}>
              <div className={`max-w-[70%] rounded-2xl px-4 py-2.5 ${
                m.role === "user"
                  ? "bg-ink/[0.04] text-ink"
                  : "bg-gradient-to-r from-deep-violet to-magenta text-white"
              }`}>
                <p className="text-[13px]">{m.content}</p>
                <p className={`mt-1 text-[10px] ${m.role === "user" ? "text-ink/30" : "text-white/50"}`}>{m.time}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-3 flex gap-2">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          className="flex-1 rounded-xl border border-ink/[0.08] bg-white px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.06]"
        />
        <button className="flex h-10 items-center justify-center rounded-xl bg-gradient-to-r from-deep-violet to-magenta px-5 text-[13px] font-semibold text-white transition hover:shadow-md active:scale-[0.98]">
          Send
        </button>
      </div>
    </div>
  );
}
