import { apiFetch } from "@/lib/api-rag";

/*
 * Leads: people the messaging engine is converting while chatting on the
 * tenant's channels. The pipeline writes the rows and schedules the
 * follow-ups; everything here only reads, moves stages, and edits the
 * tenant's follow-up knobs (the API clamps them before storing).
 */

export type LeadStage = "new" | "qualified" | "follow_up" | "converted" | "lost";

/** "important" = the AI could not resolve the thread and a human was emailed. */
export type LeadPriority = "normal" | "important";

export type Lead = {
  id: string;
  channel_id: string;
  platform: string;
  contact_id: string;
  contact_name: string | null;
  contact_username: string | null;
  language: string;
  intent: string | null;
  request: string | null;
  avatar_url: string | null;
  summary: string | null;
  stage: LeadStage;
  phone_number: string | null;
  phone_status: "stated" | "verified" | null;
  opt_out: boolean;
  next_action_at: string | null;
  priority: LeadPriority;
  /** Consecutive "AI replied, customer wrote again" cycles so far. */
  ai_miss_count: number;
  priority_since: string | null;
  /** Unified-inbox thread key — deep-links the lead to its conversation. */
  thread_key: string | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
};

export type LeadSettings = {
  enabled: boolean;
  first_nudge_minutes: number;
  second_followup_hours: number;
  final_followup_hours: number;
  max_attempts: number;
  quiet_start_hour: number;
  quiet_end_hour: number;
  timezone: string;
  /** Escalate after this many consecutive AI-answered-then-ignored cycles. */
  escalation_threshold: number;
  /** How long the AI stays muted before the thread is handed back. */
  escalation_resume_hours: number;
  /** Window before the single reminder email. */
  escalation_reminder_hours: number;
  /** Empty = escalate to the tenant owner's own signup email. */
  escalation_emails: string[];
};

export async function fetchLeads(
  params?: {
    platform?: string;
    stage?: LeadStage;
    priority?: LeadPriority;
    priorityFirst?: boolean;
    limit?: number;
    offset?: number;
  },
): Promise<{ leads: Lead[]; total: number }> {
  const qs = new URLSearchParams();
  if (params?.platform) qs.set("platform", params.platform);
  if (params?.stage) qs.set("stage", params.stage);
  if (params?.priority) qs.set("priority", params.priority);
  if (params?.priorityFirst) qs.set("priority_first", "true");
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch(`/api/v1/leads${suffix}`);
}

export async function updateLead(
  id: string,
  patch: { stage?: LeadStage; summary?: string },
): Promise<Lead> {
  return apiFetch(`/api/v1/leads/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function fetchLeadSettings(): Promise<LeadSettings> {
  return apiFetch(`/api/v1/leads/settings`);
}

export async function updateLeadSettings(
  patch: Partial<LeadSettings>,
): Promise<LeadSettings> {
  return apiFetch(`/api/v1/leads/settings`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}
