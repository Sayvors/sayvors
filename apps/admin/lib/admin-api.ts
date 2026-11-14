"use client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// The admin session lives in an httpOnly cookie set by the API
// (POST /api/v1/admin/login). JS can never read it, so there is no token
// storage here — session state is checked via GET /api/v1/admin/me.
// Every request must carry credentials (cross-origin :3001 → :8000) plus
// the X-Requested-With header the API's cookie CSRF check requires.
const ADMIN_HEADERS = { "X-Requested-With": "XMLHttpRequest" };

export async function checkAdminSession(): Promise<boolean> {
  if (typeof window === "undefined") return false;
  try {
    const res = await fetch(`${API}/api/v1/admin/me`, {
      headers: { ...ADMIN_HEADERS },
      credentials: "include",
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function adminLogin(username: string, password: string): Promise<{ expires_in_minutes: number }> {
  const res = await fetch(`${API}/api/v1/admin/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...ADMIN_HEADERS },
    credentials: "include",
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(extractDetail(text, res.status));
  }
  return res.json();
}

export async function adminLogout(): Promise<void> {
  try {
    await fetch(`${API}/api/v1/admin/logout`, {
      method: "POST",
      headers: { ...ADMIN_HEADERS },
      credentials: "include",
    });
  } catch {
    /* clearing server state is best-effort; the cookie is httpOnly */
  }
}

export async function adminFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const res = await fetch(`${API}${path}`, {
      ...options,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...ADMIN_HEADERS,
        ...(options.headers as Record<string, string>),
      },
      signal: controller.signal,
    });
    if (res.status === 401 || res.status === 403) {
      throw new Error("Admin session expired. Please log in again.");
    }
    if (!res.ok) throw new Error(extractDetail(await res.text().catch(() => ""), res.status));
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Request timed out. Try again.");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

function extractDetail(text: string, status: number): string {
  try {
    const data = JSON.parse(text);
    const detail = data?.detail;
    if (typeof detail === "string" && detail) return detail.slice(0, 200);
    // FastAPI validation errors arrive as a list of {loc, msg, type}. Showing
    // "Request failed (422)" hides which field the operator needs to fix.
    if (Array.isArray(detail) && detail.length > 0) {
      const parts = detail.slice(0, 4).map((item: unknown) => {
        const entry = (item ?? {}) as { loc?: unknown; msg?: unknown };
        const loc = Array.isArray(entry.loc)
          ? entry.loc.filter((p) => p !== "body" && p !== "query").join(".")
          : "";
        const msg = typeof entry.msg === "string" ? entry.msg : "Invalid value";
        return loc ? `${loc}: ${msg}` : msg;
      });
      return parts.join("; ").slice(0, 300);
    }
  } catch {
    /* not JSON */
  }
  return `Request failed (${status}).`;
}

// ── Tenant lifecycle (suspend / export / purge) ─────────────────────────

export async function suspendTenant(
  id: string,
  reason?: string,
): Promise<AdminTenantDetail> {
  return adminFetch<AdminTenantDetail>(
    `/api/v1/admin/tenants/${encodeURIComponent(id)}/suspend`,
    { method: "POST", body: JSON.stringify({ reason: reason?.trim() || null }) },
  );
}

export async function reactivateTenant(id: string): Promise<AdminTenantDetail> {
  return adminFetch<AdminTenantDetail>(
    `/api/v1/admin/tenants/${encodeURIComponent(id)}/reactivate`,
    { method: "POST" },
  );
}

export async function purgeTenant(
  id: string,
  confirm: string,
): Promise<{ tenant_id: string; total_rows: number; deleted: Record<string, number> }> {
  return adminFetch(`/api/v1/admin/tenants/${encodeURIComponent(id)}/purge`, {
    method: "POST",
    body: JSON.stringify({ confirm }),
  });
}

/** Download the tenant export as a file. Kept out of adminFetch because the
 *  response is a JSON attachment, not an object we render. */
export async function downloadTenantExport(id: string): Promise<void> {
  const res = await fetch(
    `${API}/api/v1/admin/tenants/${encodeURIComponent(id)}/export`,
    { headers: { ...ADMIN_HEADERS }, credentials: "include" },
  );
  if (res.status === 401 || res.status === 403) {
    throw new Error("Admin session expired. Please log in again.");
  }
  if (!res.ok) {
    throw new Error(extractDetail(await res.text().catch(() => ""), res.status));
  }
  const disposition = res.headers.get("content-disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match?.[1] || `sayvors-tenant-${id}.json`;
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export async function fetchOverviewStats(window: string): Promise<OverviewStats> {
  return adminFetch<OverviewStats>(`/api/v1/admin/overview/stats?window=${encodeURIComponent(window)}`);
}

export async function fetchLiveStats(minutes: 30 | 60): Promise<LiveStats> {
  return adminFetch<LiveStats>(`/api/v1/admin/overview/stats/live?minutes=${minutes}`);
}

export async function fetchAdminHealth(): Promise<AdminHealth> {
  return adminFetch<AdminHealth>("/api/v1/admin/health");
}

export interface EmailStats {
  days: number;
  outbox: Record<string, number>;
  events: Record<string, number>;
  suppressed: number;
}

export async function fetchEmailStats(days: number): Promise<EmailStats> {
  return adminFetch<EmailStats>(
    `/api/v1/admin/email/stats?days=${encodeURIComponent(String(days))}`,
  );
}

export interface EmailCampaign {
  id: string;
  name: string;
  subject: string;
  status: "draft" | "running" | "completed" | "cancelled";
  created_by: string | null;
  total_recipients: number;
  expanded_recipients: number;
  queued: number;
  sent: number;
  failed: number;
  dead: number;
  cancelled: number;
  suppressed: number;
  batch_size: number;
  interval_seconds: number;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  cancelled_at: string | null;
}

export interface CampaignAudienceItem {
  id: string;
  tenant_id: string;
  email: string | null;
  first_name: string | null;
  suppressed: boolean;
}

export interface CampaignVariable {
  key: string;
  label: string;
  example: string;
}

export interface CampaignTemplate {
  id: string;
  name: string;
  description: string;
  subject: string;
  body_html: string;
}

export async function fetchCampaignTemplates(): Promise<{
  items: CampaignTemplate[];
}> {
  return adminFetch<{ items: CampaignTemplate[] }>(
    "/api/v1/admin/email/campaigns/templates",
  );
}

export interface CampaignPreview {
  tenant: { name: string | null; email: string | null };
  subject: string;
  body_html: string;
  text: string | null;
  html: string;
}

export async function fetchCampaignVariables(): Promise<{
  items: CampaignVariable[];
}> {
  return adminFetch<{ items: CampaignVariable[] }>(
    "/api/v1/admin/email/campaigns/variables",
  );
}

export async function previewEmailCampaign(input: {
  subject: string;
  html: string;
  text?: string | null;
}): Promise<CampaignPreview> {
  return adminFetch<CampaignPreview>("/api/v1/admin/email/campaigns/preview", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export interface CampaignAudience {
  eligible: number;
  max_recipients: number;
  items: CampaignAudienceItem[];
}

export interface CampaignRecipient {
  id: string;
  tenant_id: string | null;
  email: string;
  status:
    | "queued"
    | "sending"
    | "sent"
    | "failed"
    | "dead"
    | "cancelled"
    | "suppressed";
  attempts: number;
  error: string | null;
  last_event: string | null;
  last_event_detail: string | null;
  last_event_at: string | null;
  created_at: string | null;
  sent_at: string | null;
}

export interface CampaignRecipients {
  items: CampaignRecipient[];
  total: number;
  counts: Record<string, number>;
}

export async function fetchEmailCampaigns(): Promise<{ items: EmailCampaign[] }> {
  return adminFetch<{ items: EmailCampaign[] }>("/api/v1/admin/email/campaigns");
}

export async function fetchCampaignAudience(
  limit = 50,
  offset = 0,
): Promise<CampaignAudience> {
  return adminFetch<CampaignAudience>(
    `/api/v1/admin/email/campaigns/audience?limit=${limit}&offset=${offset}`,
  );
}

export async function fetchCampaignRecipients(
  id: string,
  status?: string,
  limit = 50,
  offset = 0,
): Promise<CampaignRecipients> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (status) params.set("status", status);
  return adminFetch<CampaignRecipients>(
    `/api/v1/admin/email/campaigns/${encodeURIComponent(id)}/recipients?${params}`,
  );
}

export async function createEmailCampaign(input: {
  name?: string;
  subject: string;
  html: string;
  text?: string | null;
  batch_size?: number;
  interval_seconds?: number;
}): Promise<EmailCampaign> {
  return adminFetch<EmailCampaign>("/api/v1/admin/email/campaigns", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function startEmailCampaign(id: string): Promise<EmailCampaign> {
  return adminFetch<EmailCampaign>(
    `/api/v1/admin/email/campaigns/${encodeURIComponent(id)}/start`,
    { method: "POST" },
  );
}

export async function cancelEmailCampaign(id: string): Promise<EmailCampaign> {
  return adminFetch<EmailCampaign>(
    `/api/v1/admin/email/campaigns/${encodeURIComponent(id)}/cancel`,
    { method: "POST" },
  );
}

export interface PurgedAccount {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  reason: string;
  status: "pending" | "purged" | "failed";
  error: string | null;
  signed_up_at: string | null;
  purged_at: string | null;
  metadata: Record<string, unknown>;
}

export async function fetchPurgedAccounts(
  limit = 50,
  offset = 0,
  q = "",
): Promise<{ items: PurgedAccount[]; total: number }> {
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  if (q.trim()) params.set("q", q.trim());
  return adminFetch<{ items: PurgedAccount[]; total: number }>(
    `/api/v1/admin/purged-accounts?${params}`,
  );
}

export async function runUnverifiedPurge(): Promise<{ purged: number }> {
  return adminFetch<{ purged: number }>("/api/v1/admin/purged-accounts/run", {
    method: "POST",
  });
}

export interface AdminOverview {
  users_total: number;
  users_verified: number;
  signups_last_7d: number;
  connections: number;
  last_synced_at: string | null;
  reviews_total: number;
  posts_total: number;
  posts_by_status: Record<string, number>;
  databanks_total: number;
  documents_total: number;
  outbox_pending: number;
  outbox_failed: number;
  ingest_failed: number;
}

export interface AdminTenant {
  id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  email_verified: boolean;
  created_at: string | null;
  has_connection: boolean;
  listing_name: string | null;
  last_synced_at: string | null;
  reviews: number;
  posts: number;
  databanks: number;
  suspended_at?: string | null;
  suspension_reason?: string | null;
}

export interface AdminTenantDetail extends AdminTenant {
  recent_reviews: {
    id: string;
    rating: number;
    text: string;
    reviewer: string | null;
    sentiment: string;
    replied: boolean;
    created_at: string | null;
  }[];
  recent_posts: {
    id: string;
    title: string;
    status: string;
    created_at: string | null;
  }[];
}

// ── Meta delivery reconciliation ────────────────────────────────────────

export interface DeliveryBucket {
  inbound: number;
  outbound: number;
  outbound_with_id: number;
  outbound_without_id: number;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  delivery_rate_pct: number | null;
}

export interface DeliveryChannel extends DeliveryBucket {
  channel_id: string;
  name: string;
  platform: string;
  status: string;
}

export interface DeliveryDay extends DeliveryBucket {
  day: string;
}

export interface DeliveryReconciliation {
  days: number;
  window_start: string;
  generated_at: string;
  platforms: string[];
  totals: DeliveryBucket;
  by_channel: DeliveryChannel[];
  daily: DeliveryDay[];
  notes: string[];
}

export async function fetchTenantDelivery(
  id: string,
  days = 30,
): Promise<DeliveryReconciliation> {
  return adminFetch<DeliveryReconciliation>(
    `/api/v1/admin/tenants/${encodeURIComponent(id)}/delivery?days=${days}`,
  );
}

// ── Tenant purchase requests ────────────────────────────────────────────

export interface AdminBillingRequest {
  id: string;
  tenant_id: string;
  email: string | null;
  kind: "messages" | "channels" | "ai_credit" | "plan";
  amount: number | null;
  plan_slug: string | null;
  note: string | null;
  status: "pending" | "approved" | "rejected";
  reviewed_by: string | null;
  reviewed_at: string | null;
  decision_note: string | null;
  created_at: string;
}

export async function fetchBillingRequests(
  status: "pending" | "approved" | "rejected" | "all" = "pending",
): Promise<AdminBillingRequest[]> {
  const qs = status === "all" ? "" : `?status=${status}`;
  const data = await adminFetch<{ items?: AdminBillingRequest[] }>(
    `/api/v1/admin/requests${qs}`,
  );
  return data?.items ?? [];
}

export async function decideBillingRequest(
  id: string,
  approve: boolean,
  note?: string,
): Promise<AdminBillingRequest> {
  return adminFetch<AdminBillingRequest>(
    `/api/v1/admin/requests/${encodeURIComponent(id)}/${approve ? "approve" : "reject"}`,
    { method: "POST", body: JSON.stringify({ note: note?.trim() || null }) },
  );
}

export interface ConfigHealthItem {
  key: string;
  ok: boolean;
  hint: string;
}

export interface ConfigHealthGroup {
  group: string;
  items: ConfigHealthItem[];
}

export interface ConfigHealth {
  checked_at: string;
  groups: ConfigHealthGroup[];
}

export async function fetchConfigHealth(): Promise<ConfigHealth> {
  return adminFetch<ConfigHealth>("/api/v1/admin/config-health");
}

export interface BudgetAlarm {
  tenant_id: string;
  email: string | null;
  plan_slug: string;
  plan_name: string;
  balance_cents: number;
  held_cents: number;
  total_cents: number;
  status: "low" | "empty" | "debt";
}

export async function fetchBudgetAlarms(
  status: "low" | "empty" | "debt" | "all" = "all",
  limit = 50,
  offset = 0,
): Promise<{ items: BudgetAlarm[]; total: number }> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (status !== "all") params.set("status", status);
  return adminFetch<{ items: BudgetAlarm[]; total: number }>(
    `/api/v1/admin/billing/budget-alarms?${params.toString()}`,
  );
}

export interface FinanceRow {
  tenant_id: string;
  email: string | null;
  month: string;
  plan_slug: string | null;
  plan_name: string | null;
  plan_price_cents: number;
  extra_cost_cents: number;
  billed_cents: number;
  credits_used_cents: number;
  actual_cost_micro: number;
  collected_cents: number;
  status: "unpaid" | "paid" | "partial";
  adjustments: Record<string, unknown>;
  note: string | null;
}

export interface FinanceResponse {
  month: string;
  items: FinanceRow[];
  total: number;
  totals: {
    expected_revenue_cents: number;
    collected_cents: number;
    infra_cost_micro: number;
    margin_micro: number;
    unpaid_count: number;
  };
}

export async function fetchFinancials(
  month: string,
  limit = 50,
  offset = 0,
): Promise<FinanceResponse> {
  const params = new URLSearchParams({ month, limit: String(limit), offset: String(offset) });
  return adminFetch<FinanceResponse>(`/api/v1/admin/financials?${params.toString()}`);
}

export async function patchFinance(
  tenantId: string,
  month: string,
  body: { status?: string; collected_cents?: number; adjustments?: Record<string, unknown>; note?: string },
): Promise<FinanceRow> {
  return adminFetch<FinanceRow>(
    `/api/v1/admin/financials/${encodeURIComponent(tenantId)}?month=${encodeURIComponent(month)}`,
    { method: "PATCH", body: JSON.stringify(body) },
  );
}

export interface AdminNotificationItem {
  id: string;
  kind: string;
  severity: string;
  title: string;
  body: string | null;
  href: string | null;
  read: boolean;
  created_at: string | null;
}

export async function fetchAdminNotifications(
  unread = false,
  limit = 50,
): Promise<{ items: AdminNotificationItem[]; unread_count: number }> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (unread) params.set("unread", "true");
  return adminFetch<{ items: AdminNotificationItem[]; unread_count: number }>(
    `/api/v1/admin/notifications?${params.toString()}`,
  );
}

export async function markAdminNotificationRead(id: string): Promise<{ marked: number }> {
  return adminFetch<{ marked: number }>(`/api/v1/admin/notifications/${id}/read`, { method: "POST" });
}

export async function markAllAdminNotificationsRead(): Promise<{ marked: number }> {
  return adminFetch<{ marked: number }>("/api/v1/admin/notifications/read-all", { method: "POST" });
}

export interface PlatformStats {
  platform: string;
  label: string;
  connected: number;
  connected_total: number;
  messages: number;
  messages_in: number;
  messages_out: number;
}

export interface OverviewTotals {
  users: number;
  tenants: number;
  businesses: number;
  reviews: number;
  messages: number;
  posts: number;
}

export interface OverviewWindowDelta {
  users: number;
  tenants: number;
  businesses: number;
  reviews: number;
  messages: number;
  messages_in: number;
  messages_out: number;
  ai_replies: number;
  posts: number;
}

export interface OverviewLast24h {
  users: number;
  reviews: number;
  messages: number;
  messages_in: number;
  messages_out: number;
  ai_replies: number;
}

export interface OverviewStats {
  window: string;
  window_start: string | null;
  generated_at: string | null;
  totals: OverviewTotals;
  window_delta: OverviewWindowDelta;
  last_24h: OverviewLast24h;
  platforms: PlatformStats[];
}

export interface LiveStats {
  minutes: number;
  generated_at: string | null;
  messages: number;
  messages_in: number;
  messages_out: number;
  ai_replies: number;
  new_users: number;
  new_reviews: number;
  businesses_connected: number;
  businesses_disconnected: number;
  active_platforms: number;
  top_platform: string | null;
}

export interface HealthService {
  name: string;
  kind: string;
  ok: boolean;
  latency_ms: number;
  detail: string;
  enabled: boolean;
  key_source: string;
}

export interface HealthFailure {
  source: string;
  type: string;
  message: string;
  at: string | null;
}

export interface AdminHealth {
  status: string;
  checked_at: string | null;
  uptime_seconds: number;
  probe: boolean;
  services: HealthService[];
  recent_failures: HealthFailure[];
}
