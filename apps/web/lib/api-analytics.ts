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
  impressions_search?: number;
  website_clicks: number;
  call_clicks: number;
  direction_requests: number;
  messages?: number;
  bookings?: number;
  customer_actions?: number;
}

export interface ReviewMeaning {
  intent?: string | null;
  /** Always one of the closed vocabulary. Never free text. */
  subject?: string;
  problem?: string | null;
  asks?: string[];
  entities?: { product?: string[]; location?: string[]; staff?: string[]; dates?: string[] };
  /** The customer denies the thing (e.g. "no problems"). Never read as a complaint. */
  negated?: boolean;
  intensity?: number;
  /** Spans copied verbatim from the review. Empty means nothing was grounded. */
  evidence?: string[];
  confidence?: number;
  /** True when the reading could not be trusted and a person must look. */
  needs_human?: boolean;
  source?: "llm" | "heuristic" | "human";
  reason?: string | null;
  language?: string;
  corrected_at?: string | null;
  correction_note?: string | null;
}

export interface IssueEvidence {
  review_id: string;
  /** Verbatim span from the review — the meaning layer checked it is there. */
  quote: string;
  rating: number;
}

/**
 * One tracked problem at one location.
 *
 * `subject` is always a member of the closed vocabulary, and `status` is the
 * merchant's to set — a refresh updates the evidence and counts but never
 * reopens or closes an issue, so `avg_rating` before and after `resolved_at`
 * stays a fair comparison.
 */
export interface LocationIssue {
  id: string;
  channel_id: string;
  channel_name: string | null;
  subject: string;
  subject_label: string;
  review_count: number;
  negative_count: number;
  avg_rating: number;
  evidence: IssueEvidence[];
  title: string;
  detail: string;
  status: "open" | "in_progress" | "done" | "dismissed";
  resolution_note: string | null;
  resolved_at: string | null;
  assignee_kind: string | null;
  assignee_ref: string | null;
  notified_at: string | null;
  first_seen_at: string;
  last_seen_at: string;
}

export interface IssueListResponse {
  items: LocationIssue[];
  /** Reviews that exist but could not be categorised. Never hidden. */
  held_out: { total: number; reviewable: number; reviews: number };
  counts: Record<string, number>;
}

export interface ReviewInsight {
  id: string;
  channel_id: string;
  review_id: string;
  rating: number;
  review_text: string | null;
  reviewer_name: string | null;
  reviewer_photo_url: string | null;
  sentiment: "positive" | "neutral" | "negative";
  sentiment_score: number;
  topics: { name: string; sentiment: string }[];
  products: { name: string; sentiment: string }[];
  problems: { name: string; severity: string }[];
  replied: boolean;
  replied_at: string | null;
  /** Photos the reviewer attached. `url` is our own copy, not Google's expiring link. */
  media?: { url?: string | null; kind?: string; label?: string | null }[];
  /** Set when a complete sync stopped returning the review — Google dropped it. */
  removed_at?: string | null;
  /**
   * Per-review meaning. `subject` is always one of a fixed vocabulary and
   * `evidence` spans are always verbatim from the review, so a reading can be
   * checked rather than trusted. `source` is "llm" | "heuristic" | "human";
   * a human correction is never overwritten by a re-analysis.
   */
  meaning?: ReviewMeaning | null;
  /** Merchant flagged the review as a likely policy violation. */
  abuse_flagged?: boolean;
  /** Advisory model score 0..1. Never acts on its own. */
  abuse_score?: number | null;
  abuse_labels?: string[];
  /** Human decision: undefined (unreviewed) | "confirmed" | "dismissed". */
  abuse_verdict?: string | null;
  abuse_note?: string | null;
  /** Set once the merchant confirms they filed the report with Google. */
  abuse_reported_at?: string | null;
  skipped?: boolean;
  edited: boolean;
  edited_at: string | null;
  previous_rating: number | null;
  previous_review_text: string | null;
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

export function fetchIssues(params?: {
  channelId?: string | null;
  status?: string | null;
}): Promise<IssueListResponse> {
  const q = new URLSearchParams();
  if (params?.channelId) q.set("channel_id", params.channelId);
  if (params?.status) q.set("status", params.status);
  const qs = q.toString();
  return apiFetch(`/api/v1/analytics/issues${qs ? `?${qs}` : ""}`);
}

/** Recompute issues from current review meaning. Never changes a status. */
export function refreshIssues(channelId?: string | null): Promise<{
  created: number;
  updated: number;
  held_out: Record<string, number>;
}> {
  const q = channelId ? `?channel_id=${encodeURIComponent(channelId)}` : "";
  return apiFetch(`/api/v1/analytics/issues/refresh${q}`, { method: "POST" });
}

export function updateIssue(
  id: string,
  patch: { status?: LocationIssue["status"]; resolution_note?: string | null }
): Promise<LocationIssue> {
  return apiFetch(`/api/v1/analytics/issues/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function fetchOverview(
  days: number,
  channelId?: string | null
): Promise<Overview> {
  const params = new URLSearchParams({ days: String(days) });
  if (channelId) params.set("channel_id", channelId);
  return apiFetch(`/api/v1/analytics/overview?${params.toString()}`);
}

export interface PulseSource {
  platform: string;
  count: number;
}

export interface ReputationPulse {
  avg_rating: number;
  rating_delta: number | null;
  new_reviews: number;
  new_reviews_delta_pct: number | null;
  response_rate: number;
  awaiting_reply: number;
  oldest_wait_days: number | null;
  sources: PulseSource[];
  last_synced_at: string | null;
}

export interface WaitingPulse {
  unanswered_texts: number;
  missed_calls: number | null;
  missed_calls_available: boolean;
  median_first_response_seconds: number | null;
  waiting_over_1h: number;
  oldest_unanswered_seconds: number | null;
  business_hours: Record<string, unknown> | null;
  as_of: string | null;
}

export interface LocationPulse {
  channel_id: string;
  name: string;
  platform: string;
  new_reviews: number;
  avg_rating: number | null;
  response_rate: number;
  unanswered: number;
  below_threshold: boolean;
}

export interface OneThingPulse {
  kind: string;
  category: string;
  mentions: number;
  trend_pct: number | null;
  status: string | null;
  staff_named: number;
  serious: number;
  top_terms: { name: string; mentions: number }[];
  period_days: number;
}

export interface AttentionItem {
  kind: string;
  severity: string;
  title: string;
  detail: string | null;
  href: string | null;
}

export interface PulseResponse {
  as_of: string;
  period_days: number;
  reputation: ReputationPulse;
  waiting: WaitingPulse;
  // Optional so a frontend deploy can land before the API restart that adds
  // them; the cards default to an empty list / null rather than crashing.
  locations?: LocationPulse[];
  one_thing?: OneThingPulse | null;
  attention?: AttentionItem[];
}

export async function fetchPulse(
  days: number,
  channelId?: string | null
): Promise<PulseResponse> {
  const params = new URLSearchParams({ days: String(days) });
  if (channelId) params.set("channel_id", channelId);
  return apiFetch(`/api/v1/analytics/pulse?${params.toString()}`);
}

export interface ThemeCard {
  name: string;
  mentions: number;
  negative: number;
  negative_pct: number;
  trend_pct: number | null;
  top_location: string | null;
  quote: string | null;
}

export interface WhatChanged {
  low_reviews: number;
  prior_low_reviews: number;
  theme: string | null;
  location: string | null;
  example: string | null;
  period_days: number;
}

export interface LocationSentiment {
  channel_id: string;
  name: string;
  avg_rating: number | null;
  rating_trend: number | null;
  top_negative_theme: string | null;
  response_rate: number;
  unanswered: number;
}

export interface InsightsSummaryBullet {
  text: string;
  n: number;
}

export interface InsightsSummary {
  bullets: InsightsSummaryBullet[];
  review_count: number;
  confidence: string;
  source: string;
  analyzed_at: string;
}

export interface ActionCard {
  id: string;
  subject: string;
  title: string;
  detail: string;
  status: string;
  negative_count: number;
  review_count: number;
}

export interface InsightsCards {
  days: number;
  top_themes: ThemeCard[];
  what_changed: WhatChanged;
  sentiment_by_location: LocationSentiment[];
  summary: InsightsSummary;
  action_plan: ActionCard[];
}

export async function fetchInsightsCards(
  days: number,
  channelId?: string | null
): Promise<InsightsCards> {
  const params = new URLSearchParams({ days: String(days) });
  if (channelId) params.set("channel_id", channelId);
  return apiFetch(`/api/v1/analytics/insights-cards?${params.toString()}`);
}

export interface FunnelChannel {
  channel: string;
  requests: number;
}

export interface FunnelTrigger {
  trigger: string;
  requests: number;
}

export interface ReviewFunnel {
  requests_sent: number;
  delivered: number;
  clicked: number;
  reviews: number;
  reviews_via_request: number;
  conversion_rate: number | null;
  avg_rating: number | null;
  delivery_tracked: boolean;
  click_tracked: boolean;
  by_channel: FunnelChannel[];
  by_trigger: FunnelTrigger[];
}

export interface GrowthContacts {
  new_contacts: number;
  prior_contacts: number;
  delta_pct: number | null;
  by_platform: { platform: string; contacts: number }[];
  attribution: string;
}

export interface GrowthAction {
  kind: string;
  title: string;
  detail: string;
  expected: string | null;
  href: string | null;
}

export interface GrowthCards {
  days: number;
  funnel: ReviewFunnel;
  contacts: GrowthContacts;
  retention: { available: boolean; reason: string | null };
  actions: GrowthAction[];
}

export async function fetchGrowthCards(
  days: number,
  channelId?: string | null
): Promise<GrowthCards> {
  const params = new URLSearchParams({ days: String(days) });
  if (channelId) params.set("channel_id", channelId);
  return apiFetch(`/api/v1/analytics/growth-cards?${params.toString()}`);
}

export async function recordReviewRequest(input: {
  channel_id?: string | null;
  contact?: string | null;
  contact_name?: string | null;
  channel?: "whatsapp" | "sms" | "email" | "in_person";
  trigger?: "manual" | "qr" | "after_visit" | "campaign";
}): Promise<void> {
  await apiFetch("/api/v1/analytics/review-requests", {
    method: "POST",
    body: JSON.stringify(input),
  });
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

export function dismissReviewEdit(insightId: string): Promise<ReviewInsight> {
  return apiFetch(`/api/v1/analytics/reviews/insights/${insightId}/dismiss-edit`, {
    method: "POST",
  });
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
  category: string;
  mentions: number;
  severity: string;
  trend_pct: number | null;
  status: string;
  impact_score: number;
  staff_named: number;
  serious: number;
}

export interface ComplaintTerm {
  name: string;
  mentions: number;
}

export interface ComplaintArea {
  category: string;
  mentions: number;
  staff_named: number;
  serious: number;
  trend_pct: number | null;
  status: string;
  top_terms: ComplaintTerm[];
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
  by_area: ComplaintArea[];
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

export interface KeywordStat {
  keyword: string;
  impressions: number;
  trend_pct: number | null;
}

export interface KeywordsResponse {
  days: number;
  available: boolean;
  keywords: KeywordStat[];
}

export const fetchKeywords = (days: number, channelId?: string | null): Promise<KeywordsResponse> =>
  apiFetch(`/api/v1/analytics/growth/keywords?${qs(days, channelId)}`);

/* ── Messaging overview (WhatsApp / IG / FB, from the rollup table) ── */

export interface MessagingChannelRow {
  channel_id: string;
  platform: string;
  label: string;
  messages_in: number;
  messages_out: number;
  ai_handled_out: number;
  human_handled_out: number;
  messages_in_prev: number;
  conversations: number;
  conversations_prev: number;
  response_rate: number | null;
  median_first_response_seconds: number | null;
  unanswered_now: number | null;
  comments_in: number;
  comments_replied: number;
}

export interface MessagingTotals {
  messages_in: number;
  messages_out: number;
  ai_handled_out: number;
  ai_handled_out_prev: number;
  human_handled_out: number;
  human_handled_out_prev: number;
  messages_in_prev: number;
  messages_out_prev: number;
  conversations: number;
  conversations_prev: number;
  response_rate: number | null;
  response_rate_prev: number | null;
  median_first_response_seconds: number | null;
  median_first_response_seconds_prev: number | null;
  p90_first_response_seconds: number | null;
  unanswered_now: number | null;
  oldest_unanswered_seconds: number | null;
  as_of: string | null;
}

export interface MessagingOverview {
  days: number;
  /** Meta's own "Very responsive" gate: 90% answered, median < 15 min. */
  goal: { response_rate: number; median_seconds: number };
  totals: MessagingTotals;
  channels: MessagingChannelRow[];
  by_hour_in: number[];
}

export const fetchMessagingOverview = (
  days: number,
  channelId?: string | null
): Promise<MessagingOverview> =>
  apiFetch(`/api/v1/analytics/messaging/overview?${qs(days, channelId)}`);

export type MessagingGrowthResponse = {
  days: number;
  customer_growth: { week: string; new_contacts: number; messages_in: number; messages_out: number; conversations: number }[];
  total_new_contacts: number;
  total_messages_in: number;
  total_messages_out: number;
  follower_growth: {
    first: number;
    last: number;
    net: number;
    rate_pct: number | null;
    snapshots: { date: string; count: number }[];
    collecting: boolean;
  } | null;
};

export const fetchMessagingGrowth = (
  days: number,
  channelId?: string | null
): Promise<MessagingGrowthResponse> =>
  apiFetch(`/api/v1/analytics/messaging/growth?${qs(days, channelId)}`);

export const fetchConversationInsights = (): Promise<{
  insights: Record<string, unknown>;
  message_count: number;
  window_start: string | null;
  window_end: string | null;
  computed_at: string | null;
}> => apiFetch("/api/v1/analytics/conversations/insights");

export const fetchMarketBenchmarks = (metric?: string): Promise<{
  date: string;
  scope_market: string;
  scope_network: string;
  metric: string;
  median: number | null;
  p25: number | null;
  p75: number | null;
  business_count: number;
}[]> => apiFetch(`/api/v1/analytics/market-benchmarks${metric ? `?metric=${encodeURIComponent(metric)}` : ""}`);

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
  branches: BranchBenchmark[];
  leader: BranchHighlight | null;
  needs_attention: BranchHighlight | null;
  recommendations: BranchRecommendation[];
  top_services: ServiceHighlight[];
  needs_fix_services: ServiceHighlight[];
  top_topics: { name: string; mentions: number }[];
  distribution?: Record<string, { best: number; median: number; worst: number; gap: number }> | null;
  portfolio_health_score?: number | null;
  portfolio_action_rate?: number | null;
  portfolio_velocity_per_month?: number | null;
  portfolio_impressions?: number | null;
  portfolio_actions?: number | null;
  plain_summary?: string | null;
  // Tenant-cohort market view: your branches ranked against every other
  // Sayvors business in your city + category. Tenants ARE the competitors.
  cohort?: {
    scope: string;
    label: string;
    city: string | null;
    category: string | null;
    count: number;
    competitors: MarketEntry[];
    median_rating: number | null;
    median_reviews: number | null;
    top3_median_rating: number | null;
    median_response_rate: number | null;
  } | null;
  market?: MarketEntry[];
  my_rank?: number | null;
}

export interface MarketEntry {
  name: string;
  city?: string | null;
  avg_rating: number;
  reviews_total: number;
  response_rate: number | null;
  velocity_per_month?: number | null;
  reputation_score: number;
  is_you: boolean;
  rank: number;
  channel_id?: string;
  listing_id?: string;
}

export interface ServiceHighlight {
  name: string;
  mentions: number;
  positive_pct: number;
  avg_rating: number | null;
  negative: number;
}

export interface BranchBenchmark {
  channel_id: string;
  name: string;
  avg_rating: number;
  reviews_total: number;
  positive_pct: number;
  response_rate: number;
  reputation_score: number;
  health_score?: number | null;
  rating_delta: number | null;
  reviews_delta_pct: number | null;
  velocity_ratio?: number | null;
  reviews_last_period?: number;
  velocity_per_month?: number | null;
  impressions_maps?: number;
  customer_actions: number;
  action_rate?: number | null;
  gap_vs_leader_per_year?: number | null;
  top_problem: string | null;
  top_problem_mentions: number;
  rank: number;
}

export interface BranchHighlight {
  channel_id: string;
  name: string;
  reasons: string[];
}

export interface BranchRecommendation {
  channel_id: string;
  name: string;
  priority: string;
  text: string;
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
  generation_attempt?: number;
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

export function editReply(channelId: string, replyId: string, replyText: string): Promise<ReviewReplyDTO> {  return apiFetch(`/api/v1/channels/${channelId}/reviews/${replyId}`, {
    method: "PUT",
    body: JSON.stringify({ reply_text: replyText }),
  });
}

export function regenerateReply(channelId: string, replyId: string, engine = false): Promise<ReviewReplyDTO> {
  return apiFetch(`/api/v1/channels/${channelId}/reviews/${replyId}/regenerate${engine ? "?engine=true" : ""}`, { method: "POST" });
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

/**
 * Correct what the AI understood a review to mean.
 *
 * The AI once read the Arabic review "you need to fix your building" as
 * "bank account corrections" and produced a business action from that
 * fabrication. This is the human gate that lets a person fix the reading at
 * the source. The correction is stored as `source: "human"` and re-analysis
 * will not overwrite it.
 */
export function correctReviewMeaning(
  insightId: string,
  patch: {
    subject?: string;
    intent?: string | null;
    problem?: string | null;
    asks?: string[];
    needs_human?: boolean;
    note?: string | null;
  }
): Promise<ReviewInsight> {
  return apiFetch(`/api/v1/analytics/reviews/insights/${encodeURIComponent(insightId)}/meaning`, {
    method: "POST",
    body: JSON.stringify(patch),
  });
}
