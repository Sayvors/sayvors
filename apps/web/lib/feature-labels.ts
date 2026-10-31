/* Canonical feature labels, shared by the tenant plans page and the
 * upgrade prompt. Keys must match billing/features.py FEATURE_CATALOG. */

export const FEATURE_LABELS: Record<string, string> = {
  channels: "Messaging channels",
  messaging: "Inbox messaging",
  ai_replies: "AI replies",
  reviews: "Review management",
  posts: "Social posts",
  media: "Media library",
  analytics: "Analytics",
  automation: "Automation rules",
  databank: "Knowledge base",
  leads: "Lead pipeline",
  voice: "Voice & TTS",
  scheduling: "Scheduling",
  assistant: "AI assistant",
  social_response_style: "Social response style",
  bulk_edit_csv: "Bulk edit CSV",
  benchmarking: "Benchmarking",
  verifications: "Verifications",
  growth: "Growth insights",
  ticket_assignment: "Ticket assignment",
  voice_replies: "Voice replies (beta)",
  ask_sayvors_premium: "ASK Sayvors premium",
  priority_support: "Priority support",
  sla: "SLA guarantee",
};

export const FEATURE_ORDER: string[] = [
  "channels",
  "messaging",
  "ai_replies",
  "reviews",
  "posts",
  "media",
  "analytics",
  "automation",
  "databank",
  "leads",
  "voice",
  "scheduling",
  "assistant",
  "social_response_style",
  "bulk_edit_csv",
  "benchmarking",
  "verifications",
  "growth",
  "ticket_assignment",
  "voice_replies",
  "ask_sayvors_premium",
  "priority_support",
  "sla",
];

export function featureLabel(key: string): string {
  return FEATURE_LABELS[key] ?? key;
}
