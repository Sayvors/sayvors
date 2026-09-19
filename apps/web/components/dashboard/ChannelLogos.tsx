"use client";

import Image from "next/image";

export function ChannelLogo({ channel, className = "h-5 w-5" }: { channel: string; className?: string }) {
  const src = `/channels/${channel}.png`;
  return (
    <Image
      src={src}
      alt={channel}
      width={24}
      height={24}
      className={className}
      unoptimized
    />
  );
}

export function LLMLogo({ llm, className = "h-5 w-5" }: { llm: string; className?: string }) {
  const src = `/llms/${llm}.png`;
  return (
    <Image
      src={src}
      alt={llm}
      width={24}
      height={24}
      className={className}
      unoptimized
    />
  );
}

export function OpenAILogo({ className = "h-5 w-5" }: { className?: string }) {
  return <LLMLogo llm="chatgpt" className={className} />;
}

export function AnthropicLogo({ className = "h-5 w-5" }: { className?: string }) {
  return <LLMLogo llm="claude" className={className} />;
}

export function GoogleLogo({ className = "h-5 w-5" }: { className?: string }) {
  return <LLMLogo llm="gemini" className={className} />;
}

export function GrokLogo({ className = "h-5 w-5" }: { className?: string }) {
  return <LLMLogo llm="grok" className={className} />;
}

export function MistralLogo({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none">
      <circle cx="12" cy="12" r="11" fill="#FF7000" />
      <path d="M7 8h2.5l2.5 4-2.5 4H7l2.5-4L7 8zm5 0h2.5l2.5 4-2.5 4H12l2.5-4L12 8z" fill="white" />
    </svg>
  );
}

export const llmLogos: Record<string, React.ComponentType<{ className?: string }>> = {
  "gpt-4o": OpenAILogo,
  "gpt-4o-mini": OpenAILogo,
  "claude-3.5-sonnet": AnthropicLogo,
  "claude-3-haiku": AnthropicLogo,
  "gemini-pro": GoogleLogo,
  "grok-2": GrokLogo,
  "mistral-large": MistralLogo,
  "mistral-small": MistralLogo,
};
