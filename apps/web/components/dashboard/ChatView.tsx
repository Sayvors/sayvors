"use client";

import { useState, useRef, useEffect } from "react";
import type { Message, Conversation } from "@/lib/channel-data";

interface ChatViewProps {
  conversation: Conversation;
  messages: Message[];
  onToggleAgent: (convId: string) => void;
}

export default function ChatView({ conversation, messages, onToggleAgent }: ChatViewProps) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = () => {
    if (!input.trim() || conversation.agentMode) return;
    // Mock send — in real app this would send the message
    setInput("");
  };

  return (
    <div className="flex h-full flex-col">
      {/* Chat header */}
      <div className="flex items-center justify-between border-b border-ink/[0.04] px-4 py-2.5 dark:border-fog/[0.04]">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-deep-violet/10 text-[12px] font-semibold text-deep-violet">
            {conversation.avatar}
          </div>
          <div>
            <p className="text-[13px] font-semibold text-ink dark:text-fog">{conversation.name}</p>
            <p className="text-[11px] text-ink/40 dark:text-fog/40">
              {conversation.agentMode ? "Agent responding" : "You"}
            </p>
          </div>
        </div>

        {/* Agent/Human toggle */}
        <button
          onClick={() => onToggleAgent(conversation.id)}
          className="flex items-center gap-2"
        >
          <span className="text-[11px] font-medium text-ink/50 dark:text-fog/50">
            {conversation.agentMode ? "Agent" : "Human"}
          </span>
          <div
            className={`relative h-5 w-9 rounded-full transition-colors ${
              conversation.agentMode ? "bg-emerald-500" : "bg-ink/20 dark:bg-fog/20"
            }`}
          >
            <span
              className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform ${
                conversation.agentMode ? "translate-x-4" : "translate-x-0.5"
              }`}
            />
          </div>
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto bg-fog/30 p-4 dark:bg-ink/30">
        <div className="space-y-3">
          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === "user" ? "justify-start" : "justify-end"}`}>
              <div className={`max-w-[75%] rounded-2xl px-4 py-2.5 ${
                msg.role === "user"
                  ? "bg-white text-ink shadow-sm dark:bg-ink dark:text-fog dark:border dark:border-fog/[0.06]"
                  : "bg-gradient-to-r from-deep-violet to-magenta text-white"
              }`}>
                <p className="text-[13px]">{msg.content}</p>
                <p className={`mt-1 text-[10px] ${msg.role === "user" ? "text-ink/30 dark:text-fog/30" : "text-white/50"}`}>
                  {msg.time}
                </p>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div className="border-t border-ink/[0.04] p-3 dark:border-fog/[0.04]">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSend()}
            placeholder={conversation.agentMode ? "Agent is handling this conversation..." : "Type a message..."}
            disabled={conversation.agentMode}
            className="flex-1 rounded-xl border border-ink/[0.08] bg-white px-4 py-2.5 text-[13px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.06] disabled:cursor-not-allowed disabled:opacity-50 dark:border-fog/[0.08] dark:bg-ink dark:text-fog dark:placeholder:text-fog/30"
          />
          <button
            onClick={handleSend}
            disabled={conversation.agentMode || !input.trim()}
            className="flex h-10 items-center justify-center rounded-xl bg-gradient-to-r from-deep-violet to-magenta px-5 text-[13px] font-semibold text-white transition hover:shadow-md active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          >
            Send
          </button>
        </div>
        {conversation.agentMode && (
          <p className="mt-2 text-center text-[11px] text-ink/30 dark:text-fog/30">
            Agent is automatically responding to this conversation
          </p>
        )}
      </div>
    </div>
  );
}
