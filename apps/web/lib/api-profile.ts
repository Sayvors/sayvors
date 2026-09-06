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
  phone: string | null;
  theme: string;
  language: string;
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
  phone?: string;
}): Promise<Profile> {
  return apiFetch("/api/v1/profile", { method: "PATCH", body: JSON.stringify(data) });
}

export async function updatePreferences(theme: string, language: string): Promise<Profile> {
  return apiFetch("/api/v1/profile/preferences", {
    method: "PATCH",
    body: JSON.stringify({ theme, language }),
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
