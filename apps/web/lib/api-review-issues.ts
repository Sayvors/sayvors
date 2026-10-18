"use client";

import { apiFetch } from "./api-rag";

/**
 * Tenant-side client for /api/v1/reviews/issues — one row per classified
 * Google review that produced a ticket. Shapes mirror ReviewIssueOut in
 * services/api/app/modules/channels/review_issues.py.
 */
export interface ReviewIssue {
  id: string;
  tenant_id: string;
  channel_id: string;
  review_id: string;
  ticket_number: string | null;
  handoff_code: string | null;
  rating: number;
  primary_category: string;
  subcategory: string;
  subcategory_detail: string | null;
  intent: string;
  sentiment: string;
  priority: string;
  needs_attention: boolean;
  summary: string | null;
  status: string;
  reviewer_name: string | null;
  review_text: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface ReviewIssueList {
  issues: ReviewIssue[];
  total: number;
}

export interface ReviewIssueQuery {
  status?: string;
  priority?: string;
  channel_id?: string;
  ticketed?: boolean;
  limit?: number;
  offset?: number;
}

export const fetchReviewIssues = (q: ReviewIssueQuery = {}): Promise<ReviewIssueList> => {
  const params = new URLSearchParams();
  if (q.status) params.set("status", q.status);
  if (q.priority) params.set("priority", q.priority);
  if (q.channel_id) params.set("channel_id", q.channel_id);
  if (q.ticketed !== undefined) params.set("ticketed", String(q.ticketed));
  params.set("limit", String(q.limit ?? 200));
  params.set("offset", String(q.offset ?? 0));
  return apiFetch(`/api/v1/reviews/issues?${params.toString()}`);
};

export type ReviewIssuePatch = {
  status?: string;
  subcategory?: string;
  primary_category?: string;
  priority?: string;
  needs_attention?: boolean;
};

export const updateReviewIssue = (id: string, patch: ReviewIssuePatch): Promise<ReviewIssue> =>
  apiFetch(`/api/v1/reviews/issues/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

/**
 * Mint (or return) the code this customer quotes on WhatsApp. Idempotent on
 * the server; 422 means the issue needs no attention and has nothing to
 * hand off — a fact about the issue, not a failed request.
 */
export const mintHandoffCode = (id: string): Promise<ReviewIssue> =>
  apiFetch(`/api/v1/reviews/issues/${id}/handoff-code`, { method: "POST" });

/**
 * The wa.me deep link for a code: digits-only number, code as the prefilled
 * text. Empty string when there is no WhatsApp number connected — the page
 * shows the bare code instead of a link.
 */
export const waMeLink = (phone: string | null | undefined, code: string): string => {
  const digits = (phone ?? "").replace(/\D/g, "");
  if (!digits || !code) return "";
  return `https://wa.me/${digits}?text=${encodeURIComponent(code)}`;
};
