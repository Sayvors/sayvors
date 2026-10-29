/* WhatsApp message templates: the only legal send outside the 24h window. */

import { apiFetch } from "@/lib/api-rag";

export interface WhatsAppTemplate {
  id: string;
  name: string;
  language: string;
  category: string;
  status: "approved" | "pending" | "rejected" | "paused" | "disabled" | "draft" | string;
  body: string;
  variables: number;
  meta_template_id: string | null;
  last_synced_at: string | null;
  updated_at: string | null;
}

export interface TemplateSendResult {
  id: string;
  status: "sent" | "failed" | "blocked";
  template_name: string;
  language: string;
  contact_phone: string;
  provider_message_id: string | null;
  error: string | null;
  created_at: string | null;
  created: boolean;
}

export async function listWhatsAppTemplates(): Promise<WhatsAppTemplate[]> {
  const data = await apiFetch("/api/v1/whatsapp/templates");
  return (data?.templates ?? []) as WhatsAppTemplate[];
}

export async function syncWhatsAppTemplates(): Promise<{
  created: number;
  updated: number;
  templates: WhatsAppTemplate[];
}> {
  return (await apiFetch("/api/v1/whatsapp/templates/sync", {
    method: "POST",
  })) as { created: number; updated: number; templates: WhatsAppTemplate[] };
}

export async function sendWhatsAppTemplate(params: {
  channelId: string;
  contactPhone: string;
  templateId: string;
  variables: string[];
  idempotencyKey: string;
}): Promise<TemplateSendResult> {
  return (await apiFetch("/api/v1/whatsapp/templates/send", {
    method: "POST",
    body: JSON.stringify({
      channel_id: params.channelId,
      contact_phone: params.contactPhone,
      template_id: params.templateId,
      variables: params.variables,
      idempotency_key: params.idempotencyKey,
    }),
  })) as TemplateSendResult;
}

export async function recordWhatsAppConsent(params: {
  channelId: string;
  contactPhone: string;
  source?: string;
}): Promise<{ opt_in_at: string | null; opt_in_source: string | null }> {
  return (await apiFetch("/api/v1/whatsapp/templates/consent", {
    method: "POST",
    body: JSON.stringify({
      channel_id: params.channelId,
      contact_phone: params.contactPhone,
      source: params.source ?? "operator",
    }),
  })) as { opt_in_at: string | null; opt_in_source: string | null };
}

export async function revokeWhatsAppConsent(params: {
  channelId: string;
  contactPhone: string;
}): Promise<void> {
  const q = new URLSearchParams({
    channel_id: params.channelId,
    contact_phone: params.contactPhone,
  });
  await apiFetch(`/api/v1/whatsapp/templates/consent?${q.toString()}`, {
    method: "DELETE",
  });
}
