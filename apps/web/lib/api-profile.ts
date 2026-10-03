"use client";

import { apiFetch } from "./api-rag";

export interface Profile {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  email_verified: boolean;
  onboarded: boolean;
  bio: string | null;
  business_name: string | null;
  business_type: string | null;
  business_sells: string | null;
  business_doesnt_sell: string | null;
  business_description: string | null;
  phone: string | null;
  country: string | null;
  theme: string;
  language: string;
  /** WhatsApp response delivery: "concise" | "human" */
  response_style: string;
  /** WhatsApp voice notes tier: "off" | "simple" | "advanced" (engine is admin-managed) */
  voice_replies: string;
  plan: string;
  member_since: string;
  feedback: Record<string, number>;
}

export interface UsageItem {
  label: string;
  used: number;
  total: number;
  unit: string;
  percent: number;
}

export interface Session {
  id: string;
  device: string | null;
  ip: string | null;
  created_at: string;
}

export async function getProfile(): Promise<Profile> {
  return apiFetch("/api/v1/profile");
}

export async function updateProfile(data: {
  first_name?: string;
  last_name?: string;
  bio?: string;
  business_name?: string;
  business_type?: string | null;
  business_sells?: string | null;
  business_doesnt_sell?: string | null;
  business_description?: string | null;
  phone?: string;
  country?: string | null;
}): Promise<Profile> {
  return apiFetch("/api/v1/profile", { method: "PATCH", body: JSON.stringify(data) });
}

export async function updatePreferences(theme: string, language: string): Promise<Profile> {
  return apiFetch("/api/v1/profile/preferences", {
    method: "PATCH",
    body: JSON.stringify({ theme, language }),
  });
}

/** WhatsApp response style. Takes effect for messages sent after the save. */
export async function updateResponseStyle(responseStyle: string): Promise<Profile> {
  return apiFetch("/api/v1/profile/response-style", {
    method: "PUT",
    body: JSON.stringify({ response_style: responseStyle }),
  });
}

/** WhatsApp voice replies tier. Takes effect for messages sent after the save. */
export async function updateVoiceReplies(voiceReplies: string): Promise<Profile> {
  return apiFetch("/api/v1/profile/voice-replies", {
    method: "PUT",
    body: JSON.stringify({ voice_replies: voiceReplies }),
  });
}

export async function getUsage(): Promise<{ items: UsageItem[]; cached: boolean }> {
  return apiFetch("/api/v1/profile/usage");
}

export async function submitFeedback(category: string, stars: number): Promise<{ feedback: Record<string, number> }> {
  return apiFetch("/api/v1/profile/feedback", {
    method: "POST",
    body: JSON.stringify({ category, stars }),
  });
}

export async function getSessions(): Promise<{ sessions: Session[] }> {
  return apiFetch("/api/v1/auth/sessions");
}

export function fullName(p: Profile): string {
  return `${p.first_name} ${p.last_name}`.trim() || "Unnamed user";
}

export function initialsOf(p: Profile): string {
  const f = p.first_name?.[0] ?? "";
  const l = p.last_name?.[0] ?? "";
  return (f + l).toUpperCase() || p.email.slice(0, 2).toUpperCase();
}
