"use client";

import { apiFetch } from "./api-rag";

/** Meta's own signals for the number — quality and sending capacity. */
export interface WhatsAppHealth {
  verified_name: string | null;
  display_phone_number: string | null;
  quality_rating: string | null;
  messaging_limit_tier: string | null;
  status: string | null;
  code_verification_status: string | null;
  account_mode: string | null;
  platform_type: string | null;
}

export interface WhatsAppQrCode {
  code: string;
  prefilled_message: string;
  deep_link_url: string;
  qr_image_url?: string | null;
}

export async function fetchWhatsAppHealth(channelId: string): Promise<WhatsAppHealth> {
  return (await apiFetch(
    `/api/v1/channels/${encodeURIComponent(channelId)}/whatsapp/health`,
  )) as WhatsAppHealth;
}

export async function fetchWhatsAppQrCodes(channelId: string): Promise<WhatsAppQrCode[]> {
  return (await apiFetch(
    `/api/v1/channels/${encodeURIComponent(channelId)}/whatsapp/qr-codes`,
  )) as WhatsAppQrCode[];
}

export async function createWhatsAppQrCode(
  channelId: string,
  prefilledMessage: string,
): Promise<WhatsAppQrCode> {
  return (await apiFetch(
    `/api/v1/channels/${encodeURIComponent(channelId)}/whatsapp/qr-codes`,
    {
      method: "POST",
      body: JSON.stringify({ prefilled_message: prefilledMessage, image_format: "PNG" }),
    },
  )) as WhatsAppQrCode;
}

export async function deleteWhatsAppQrCode(
  channelId: string,
  code: string,
): Promise<{ deleted: boolean; code: string }> {
  return apiFetch(
    `/api/v1/channels/${encodeURIComponent(channelId)}/whatsapp/qr-codes/${encodeURIComponent(code)}`,
    { method: "DELETE" },
  );
}
