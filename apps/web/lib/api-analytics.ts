"use client";

import { apiFetch } from "./api-rag";

export interface SentimentSplit {
  positive: number;
  neutral: number;
  negative: number;
  positive_pct: number;
  neutral_pct: number;
  negative_pct: number;
}

export interface PeriodComparison {
  days: number;
  reviews: number;
  avg_rating: number | null;
  reviews_delta_pct: number | null;
  rating_delta: number | null;
  velocity_ratio: number | null;
}

export interface GooglePerformance {
  impressions_maps: number;
  website_clicks: number;
  call_clicks: number;
  direction_requests: number;
  customer_actions: number;
}

export interface Overview {
  total_reviews: number;
  avg_rating: number;
  rating_distribution: Record<string, number>;
  sentiment: SentimentSplit;
  response_rate: number;
  avg_response_seconds: number | null;
  unanswered: number;
  reputation_score: number;
  health_score: number;
  period: PeriodComparison;
  google_performance: GooglePerformance;
}

export interface TimeseriesPoint {
  date: string;
  channel_id: string;
  reviews_count: number;
  avg_rating: number;
  positive_count: number;
  neutral_count: number;
  negative_count: number;
  replies_count: number;
  impressions_maps: number;
  website_clicks: number;
  call_clicks: number;
  direction_requests: number;
}

export interface ReviewInsight {
  id: string;
  channel_id: string;
  review_id: string;
  rating: number;
  review_text: string | null;
  reviewer_name: string | null;
  sentiment: "positive" | "neutral" | "negative";
  sentiment_score: number;
  topics: { name: string; sentiment: string }[];
  products: { name: string; sentiment: string }[];
  problems: { name: string; severity: string }[];
  replied: boolean;
  replied_at: string | null;
  review_updated_at: string | null;
  created_at: string;
}

export interface InsightList {
  total: number;
  items: ReviewInsight[];
}

export interface ChannelOption {
  id: string;
  label: string;
}

export async function fetchOverview(
  days: number,
  channelId?: string | null
): Promise<Overview> {
  const params = new URLSearchParams({ days: String(days) });
  if (channelId) params.set("channel_id", channelId);
  return apiFetch(`/api/v1/analytics/overview?${params.toString()}`);
}

export async function fetchTimeseries(
  days: number,
  channelId?: string | null
): Promise<TimeseriesPoint[]> {
  const params = new URLSearchParams({ days: String(days) });
  if (channelId) params.set("channel_id", channelId);
  const data = await apiFetch(`/api/v1/analytics/timeseries?${params.toString()}`);
  return data.points ?? [];
}

export async function fetchInsights(opts: {
  days?: number;
  channelId?: string | null;
  sentiment?: string | null;
  rating?: number | null;
  status?: string | null;
  search?: string | null;
  limit?: number;
  offset?: number;
}): Promise<InsightList> {
  const params = new URLSearchParams();
  if (opts.channelId) params.set("channel_id", opts.channelId);
  if (opts.sentiment) params.set("sentiment", opts.sentiment);
  if (opts.rating) params.set("rating", String(opts.rating));
  if (opts.status) params.set("status", opts.status);
  if (opts.search) params.set("search", opts.search);
  params.set("limit", String(opts.limit ?? 50));
  params.set("offset", String(opts.offset ?? 0));
  return apiFetch(`/api/v1/analytics/reviews/insights?${params.toString()}`);
}

/* ── Understand pillar ─────────────────────────────────────────── */

export interface TopicStat {
  name: string;
  mentions: number;
  positive: number;
  neutral: number;
  negative: number;
  positive_pct: number;
  trend_pct: number | null;
  emerging: boolean;
}

export interface ProblemStat {
  name: string;
  mentions: number;
  severity: string;
  trend_pct: number | null;
  status: string;
  impact_score: number;
}

export interface ProductStat {
  name: string;
  mentions: number;
  positive: number;
  negative: number;
  positive_pct: number;
  avg_rating: number | null;
  trend_pct: number | null;
  emerging: boolean;
}

export interface TopicsResponse {
  days: number;
  topics: TopicStat[];
  positive_topics: string[];
  negative_topics: string[];
}

export interface ProblemsResponse {
  days: number;
  problems: ProblemStat[];
}

export interface ProductsResponse {
  days: number;
  products: ProductStat[];
  most_loved: string | null;
  most_criticized: string | null;
  fastest_growing: string | null;
}

/* ── Grow pillar ───────────────────────────────────────────────── */

export interface VisibilityResponse {
  days: number;
  impressions_maps: number;
  impressions_trend_pct: number | null;
  customer_actions: number;
  actions_trend_pct: number | null;
  click_through_pct: number | null;
}

export interface ActionStat {
  total: number;
  trend_pct: number | null;
}

export interface AcquisitionResponse {
  days: number;
  website_clicks: ActionStat;
  call_clicks: ActionStat;
  direction_requests: ActionStat;
  customer_actions: ActionStat;
}

export interface Opportunity {
  priority: number;
  type: string;
  title: string;
  detail: string;
}

export interface OpportunitiesResponse {
  days: number;
  opportunities: Opportunity[];
}

function qs(days: number, channelId?: string | null) {
  const params = new URLSearchParams({ days: String(days) });
  if (channelId) params.set("channel_id", channelId);
  return params.toString();
}

export const fetchTopics = (days: number, channelId?: string | null): Promise<TopicsResponse> =>
  apiFetch(`/api/v1/analytics/topics?${qs(days, channelId)}`);

export const fetchProblems = (days: number, channelId?: string | null): Promise<ProblemsResponse> =>
  apiFetch(`/api/v1/analytics/problems?${qs(days, channelId)}`);

export const fetchProducts = (days: number, channelId?: string | null): Promise<ProductsResponse> =>
  apiFetch(`/api/v1/analytics/products?${qs(days, channelId)}`);

export const fetchVisibility = (days: number, channelId?: string | null): Promise<VisibilityResponse> =>
  apiFetch(`/api/v1/analytics/visibility?${qs(days, channelId)}`);

export const fetchAcquisition = (days: number, channelId?: string | null): Promise<AcquisitionResponse> =>
  apiFetch(`/api/v1/analytics/acquisition?${qs(days, channelId)}`);

export const fetchOpportunities = (days: number, channelId?: string | null): Promise<OpportunitiesResponse> =>
  apiFetch(`/api/v1/analytics/opportunities?${qs(days, channelId)}`);

/* ── Benchmark pillar ─────────────────────────────────────────────── */

export interface BenchmarkResponse {
  days: number;
  current_avg_rating: number;
  similar_avg_rating: number;
  current_reviews_total: number;
  similar_reviews_total: number;
  current_sentiment_positive_pct: number;
  similar_sentiment_positive_pct: number;
  current_response_rate: number;
  similar_response_rate: number;
  current_customer_actions: number;
  similar_customer_actions: number;
  current_reputation_score: number;
  similar_reputation_score: number;
  benchmark_text: string;
  percentile_text: string;
  outperforms: string[];
  underperforms: string[];
  competitive_opportunities: string[];
  industry_trends: string[];
}

export const fetchBenchmark = (days: number, channelId?: string | null): Promise<BenchmarkResponse> => apiFetch(`/api/v1/analytics/benchmark/comparison?${qs(days, channelId)}`);

/* ── AI reply workflow (Manage pillar) ────────────────────────── */

export interface ReviewReplyDTO {
  id: string;
  channel_id: string;
  review_id: string;
  rating: number;
  review_text: string | null;
  reviewer_name: string | null;
  reply_text: string;
  status: string;
  error: string | null;
  created_at: string;
}

export function generateReply(
  channelId: string,
  body: { review_id: string; rating: number; review_text?: string | null; reviewer_name?: string | null; custom_text?: string }
): Promise<ReviewReplyDTO> {
  return apiFetch(`/api/v1/channels/${channelId}/reviews/generate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function editReply(channelId: string, replyId: string, replyText: string): Promise<ReviewReplyDTO> {
  return apiFetch(`/api/v1/channels/${channelId}/reviews/${replyId}`, {
    method: "PUT",
    body: JSON.stringify({ reply_text: replyText }),
  });
}

export function regenerateReply(channelId: string, replyId: string): Promise<ReviewReplyDTO> {
  return apiFetch(`/api/v1/channels/${channelId}/reviews/${replyId}/regenerate`, { method: "POST" });
}

export function approveReply(channelId: string, replyId: string): Promise<ReviewReplyDTO> {
  return apiFetch(`/api/v1/channels/${channelId}/reviews/${replyId}/approve`, { method: "POST" });
}

export function rejectReply(channelId: string, replyId: string): Promise<ReviewReplyDTO> {
  return apiFetch(`/api/v1/channels/${channelId}/reviews/${replyId}`, { method: "DELETE" });
}

export function retryReply(channelId: string, replyId: string): Promise<ReviewReplyDTO> {
  return apiFetch(`/api/v1/channels/${channelId}/reviews/${replyId}/retry`, { method: "POST" });
}

export interface VerifyPostedResult {
  channel_id: string;
  checked: number;
  confirmed: number;
  corrected: number;
}

export function verifyPostedReplies(channelId: string): Promise<VerifyPostedResult> {
  return apiFetch(`/api/v1/channels/${channelId}/reviews/verify-posted`, { method: "POST" });
}
