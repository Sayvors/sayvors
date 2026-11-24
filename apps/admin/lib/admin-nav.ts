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
  | "search"
  | "backups";

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
    title: "Money",
    items: [
      { href: "/billing", label: "Billing", desc: "Wallets & ledger", icon: "billing" },
      { href: "/requests", label: "Requests", desc: "Top-ups & plan requests", icon: "billing" },
      { href: "/budget-alarms", label: "Budget alarms", desc: "Low balances & debt", icon: "billing" },
      { href: "/financials", label: "Financials", desc: "Monthly per-tenant finance", icon: "billing" },
      { href: "/plans", label: "Plans", desc: "Plans & entitlements", icon: "billing" },
      { href: "/pricing", label: "Pricing", desc: "Tokens & voice rates", icon: "billing" },
      { href: "/usage", label: "Usage", desc: "Tokens & metering", icon: "usage" },
    ],
  },
  {
    title: "Operations",
    items: [
      { href: "/jobs", label: "Jobs", desc: "Queue & workers", icon: "jobs" },
      { href: "/logs", label: "Logs", desc: "Services & failures", icon: "logs" },
      { href: "/config-health", label: "Config health", desc: "API keys & env flags", icon: "logs" },
      { href: "/email", label: "Email health", desc: "Outbox, delivery, suppression", icon: "logs" },
      { href: "/email/campaigns", label: "Email campaigns", desc: "Newsletter composer & progress", icon: "logs" },
      { href: "/backups", label: "Backups", desc: "Schedule & restore", icon: "backups" },
      { href: "/retention", label: "Retention", desc: "Archive & cleanup policy", icon: "backups" },
      { href: "/purged-accounts", label: "Purged accounts", desc: "Unverified signup trace", icon: "tenants" },
    ],
  },
  {
    title: "Intelligence",
    items: [
      { href: "/llms", label: "LLMs", desc: "Providers & models", icon: "llms" },
      { href: "/ai", label: "AI image check", desc: "Banner vision model", icon: "voice" },
      { href: "/personas", label: "AI personas", desc: "Sarah & team voices", icon: "voice" },
      { href: "/voice", label: "Voice models", desc: "WhatsApp voice TTS", icon: "voice" },
      { href: "/asr", label: "Speech-to-text", desc: "ASR provider & keys", icon: "voice" },
      { href: "/embeddings", label: "Embeddings", desc: "RAG vector API", icon: "embeddings" },
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
