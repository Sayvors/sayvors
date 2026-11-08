export type NavIconName =
  | "overview"
  | "tenants"
  | "usage"
  | "logs"
  | "llms"
  | "voice"
  | "embeddings"
  | "billing"
  | "jobs"
  | "special"
  | "search";

export type NavItem = {
  href: string;
  label: string;
  desc: string;
  icon: NavIconName;
};

export const SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Platform",
    items: [
      { href: "/overview", label: "Overview", desc: "Funnel & health", icon: "overview" },
      { href: "/search", label: "Search", desc: "Tenants, models, jobs", icon: "search" },
      { href: "/tenants", label: "Tenants", desc: "Accounts & listings", icon: "tenants" },
      { href: "/special", label: "Special list", desc: "Custom feature overrides", icon: "special" },
    ],
  },
  {
    title: "Operations",
    items: [
      { href: "/usage", label: "Usage", desc: "Tokens & metering", icon: "usage" },
      { href: "/billing", label: "Billing", desc: "Wallets & ledger", icon: "billing" },
      { href: "/requests", label: "Requests", desc: "Top-ups & plan requests", icon: "billing" },
      { href: "/plans", label: "Plans", desc: "Plans & entitlements", icon: "billing" },
      { href: "/pricing", label: "Pricing", desc: "Tokens & voice rates", icon: "billing" },
      { href: "/jobs", label: "Jobs", desc: "Queue & workers", icon: "jobs" },
      { href: "/logs", label: "Logs", desc: "Services & failures", icon: "logs" },
      { href: "/email", label: "Email health", desc: "Outbox, delivery, suppression", icon: "logs" },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { href: "/llms", label: "LLMs", desc: "Providers & models", icon: "llms" },
      { href: "/personas", label: "AI personas", desc: "Sarah & team voices", icon: "voice" },
      { href: "/embeddings", label: "Embeddings", desc: "RAG vector API", icon: "embeddings" },
      { href: "/voice", label: "Voice models", desc: "WhatsApp voice TTS", icon: "voice" },
      { href: "/asr", label: "Speech-to-text", desc: "ASR provider & keys", icon: "voice" },
    ],
  },
  {
    title: "Access",
    items: [
      { href: "/operators", label: "Operators", desc: "Admin accounts", icon: "tenants" },
      { href: "/audit-log", label: "Audit log", desc: "Admin actions", icon: "logs" },
    ],
  },
];

export const FLAT_NAV = SECTIONS.flatMap((section) =>
  section.items.map((item) => ({ ...item, section: section.title })),
);
