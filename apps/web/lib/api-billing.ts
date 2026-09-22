"use client";

import { apiFetch } from "./api-rag";

export interface BillingProfile {
  id: string;
  user_id: string;
  full_name: string | null;
  email: string | null;
  phone: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country: string | null;
  tax_id: string | null;
}

export interface PaymentMethod {
  id: string;
  user_id: string;
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  holder_name: string | null;
  is_default: boolean;
  provider: string;
  verified: boolean;
  expired: boolean;
}

export async function getBillingProfile(): Promise<BillingProfile | null> {
  return apiFetch("/api/v1/billing/profile");
}

export async function saveBillingProfile(
  data: Partial<Omit<BillingProfile, "id" | "user_id">>
): Promise<BillingProfile> {
  return apiFetch("/api/v1/billing/profile", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export async function listPaymentMethods(): Promise<PaymentMethod[]> {
  return apiFetch("/api/v1/billing/methods");
}

export async function addPaymentMethod(data: {
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  holder_name?: string;
  is_default?: boolean;
  provider?: string;
  provider_token?: string;
}): Promise<PaymentMethod> {
  return apiFetch("/api/v1/billing/methods", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export interface GatewayToken {
  token: string;
  provider: string;
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  holder_name: string | null;
}

export async function tokenizeCard(data: {
  brand: string;
  last4: string;
  exp_month: number;
  exp_year: number;
  holder_name?: string;
}): Promise<GatewayToken> {
  return apiFetch("/api/v1/billing/gateway/tokenize", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export interface GatewayCharge {
  id: string;
  provider: string;
  status: string;
  amount_cents: number;
  currency: string;
  description: string | null;
}

export async function chargeCard(data: {
  token: string;
  amount_cents: number;
  currency?: string;
  description?: string;
}): Promise<GatewayCharge> {
  return apiFetch("/api/v1/billing/gateway/charge", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function setDefaultMethod(id: string): Promise<PaymentMethod> {
  return apiFetch(`/api/v1/billing/methods/${id}/default`, { method: "POST" });
}

export async function removePaymentMethod(id: string): Promise<{ ok: boolean }> {
  return apiFetch(`/api/v1/billing/methods/${id}`, { method: "DELETE" });
}

export interface Budget {
  plan: string;
  balance_cents: number;
  balance_dollars: number;
  currency: string;
}

export async function getBudget(): Promise<Budget> {
  return apiFetch("/api/v1/billing/budget");
}
