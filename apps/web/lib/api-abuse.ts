import { apiFetch } from "./api-rag";
import type { ReviewInsight } from "./api-analytics";

// -- Abusive review reporting -------------------------------------
// Google exposes no report endpoint, so the merchant files the report in
// the Business Profile UI. These calls record the decision and the triage;
// they never publish anything to Google.

export type AbuseVerdict = "confirmed" | "dismissed";

export function flagReviewAbusive(
  insightId: string,
  note?: string
): Promise<ReviewInsight> {
  return apiFetch(`/api/v1/analytics/reviews/insights/${encodeURIComponent(insightId)}/flag-abuse`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });
}

export function setAbuseVerdict(
  insightId: string,
  verdict: AbuseVerdict
): Promise<ReviewInsight> {
  return apiFetch(`/api/v1/analytics/reviews/insights/${encodeURIComponent(insightId)}/abuse-verdict`, {
    method: "POST",
    body: JSON.stringify({ verdict }),
  });
}

export function markAbuseReported(insightId: string): Promise<ReviewInsight> {
  return apiFetch(`/api/v1/analytics/reviews/insights/${encodeURIComponent(insightId)}/abuse-reported`, {
    method: "POST",
  });
}

export function clearAbuseFlag(insightId: string): Promise<ReviewInsight> {
  return apiFetch(`/api/v1/analytics/reviews/insights/${encodeURIComponent(insightId)}/clear-abuse`, {
    method: "POST",
  });
}
