/* WhatsApp message templates: the only legal send outside the 24h window.
 *
 * Templates are authored here and reviewed by Meta. The list mirrors Meta's
 * status; "sync" reconciles templates created in WhatsApp Manager.
 */

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
  send_count: number;
  sent_count: number;
  failed_count: number;
  last_sent_at: string | null;
  last_synced_at: string | null;
  updated_at: string | null;
}

export interface WabaConnection {
  connected: boolean;
  name: string | null;
}

export interface TemplateListResponse {
  templates: WhatsAppTemplate[];
  waba: WabaConnection;
}

export interface TemplateAnalytics {
  template_id: string;
  name: string;
  language: string;
  days: number;
  total: number;
  sent: number;
  failed: number;
  blocked: number;
  last_sent_at: string | null;
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

export async function listWhatsAppTemplates(): Promise<TemplateListResponse> {
  const data = await apiFetch("/api/v1/whatsapp/templates");
  return {
    templates: (data?.templates ?? []) as WhatsAppTemplate[],
    waba: (data?.waba ?? { connected: false, name: null }) as WabaConnection,
  };
}

export async function syncWhatsAppTemplates(): Promise<
  TemplateListResponse & { created: number; updated: number; remote: number }
> {
  return (await apiFetch("/api/v1/whatsapp/templates/sync", {
    method: "POST",
  })) as TemplateListResponse & {
    created: number;
    updated: number;
    remote: number;
  };
}

export async function createWhatsAppTemplate(params: {
  name: string;
  language: string;
  category: string;
  body: string;
  examples: string[];
}): Promise<WhatsAppTemplate> {
  const data = await apiFetch("/api/v1/whatsapp/templates", {
    method: "POST",
    body: JSON.stringify(params),
  });
  return data.template as WhatsAppTemplate;
}

export async function updateWhatsAppTemplate(
  templateId: string,
  params: {
    category?: string;
    body?: string;
    examples?: string[];
  },
): Promise<WhatsAppTemplate> {
  const data = await apiFetch(
    `/api/v1/whatsapp/templates/${encodeURIComponent(templateId)}`,
    {
      method: "PATCH",
      body: JSON.stringify(params),
    },
  );
  return data.template as WhatsAppTemplate;
}

export async function deleteWhatsAppTemplate(templateId: string): Promise<void> {
  await apiFetch(
    `/api/v1/whatsapp/templates/${encodeURIComponent(templateId)}`,
    { method: "DELETE" },
  );
}

export async function getWhatsAppTemplateAnalytics(
  templateId: string,
  days = 30,
): Promise<TemplateAnalytics> {
  return (await apiFetch(
    `/api/v1/whatsapp/templates/${encodeURIComponent(templateId)}/analytics?days=${days}`,
  )) as TemplateAnalytics;
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
