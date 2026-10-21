/* Customer API — the dashboard's "customers" page.

   A customer is a thread (one person on one channel). The list reuses the
   inbox's grouping and augments it with lead + Google review data; the
   detail endpoint returns the complete profile.
*/
import { apiFetch } from "@/lib/api-rag";

export interface Customer {
  key: string;
  contact_phone: string | null;
  display_name: string | null;
  username: string | null;
  avatar_url: string | null;
  channel_id: string;
  channel_name: string | null;
  platform: string | null;
  last_message: string;
  last_message_at: string;
  last_direction: string;
  message_count: number;
  unread: number;
  is_unknown: boolean;
  category?: string | null;
  priority?: string | null;
  important?: boolean;
  can_reply?: boolean;
  lead_stage?: string | null;
  intent?: string | null;
  has_review?: boolean;
}

export interface CustomerListResponse {
  customers: Customer[];
  total: number;
}

export interface CustomerIdentity {
  name: string | null;
  username: string | null;
  avatar_url: string | null;
  contact_phone: string | null;
  platform: string | null;
  channel_id: string;
  channel_name: string | null;
  profile_fetched_at: string | null;
}

export interface CustomerLead {
  id: string;
  stage: string;
  intent: string | null;
  request: string | null;
  summary: string | null;
  contact_name: string | null;
  contact_username: string | null;
  language: string;
  phone_number: string | null;
  phone_status: string;
  opt_out: boolean;
  field_provenance: Record<string, unknown> | null;
  last_message_at: string | null;
  next_action_at: string | null;
  priority: string;
  ai_miss_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface CustomerMessage {
  id: string;
  direction: "inbound" | "outbound";
  content: string;
  content_type: string;
  status: string;
  error: string | null;
  contact_name: string | null;
  created_at: string;
}

export interface CustomerReview {
  id: string;
  review_id: string;
  rating: number;
  review_text: string | null;
  reviewer_name: string | null;
  reply_text: string | null;
  status: string;
  error: string | null;
  created_at: string | null;
  replied_at: string | null;
}

export interface CustomerProfile {
  identity: CustomerIdentity;
  category: string | null;
  priority: string | null;
  important: boolean;
  can_reply: boolean;
  lead: CustomerLead | null;
  messages: CustomerMessage[];
  reviews: CustomerReview[];
}

export async function fetchCustomers(params: {
  search?: string;
  platform?: string;
  category?: string;
  priority?: string;
  important?: boolean;
  limit?: number;
  offset?: number;
} = {}): Promise<CustomerListResponse> {
  const q = new URLSearchParams();
  if (params.search) q.set("search", params.search);
  if (params.platform && params.platform !== "all") q.set("platform", params.platform);
  if (params.category && params.category !== "all") q.set("category", params.category);
  if (params.priority && params.priority !== "all") q.set("priority", params.priority);
  if (params.important) q.set("important", "true");
  q.set("limit", String(params.limit ?? 100));
  q.set("offset", String(params.offset ?? 0));
  const data = await apiFetch(`/api/v1/customers?${q.toString()}`);
  return { customers: data?.customers ?? [], total: data?.total ?? 0 };
}

export async function fetchCustomerProfile(
  channelId: string,
  contactKey: string,
): Promise<CustomerProfile> {
  return await apiFetch(`/api/v1/customers/${encodeURIComponent(channelId)}/${encodeURIComponent(contactKey)}`);
}

export async function updateCustomerCategory(
  channelId: string,
  contactKey: string,
  category: string,
  priority: string | null = null,
): Promise<void> {
  await apiFetch(`/api/v1/inbox/threads/${encodeURIComponent(channelId)}/${encodeURIComponent(contactKey)}/category`, {
    method: "PATCH",
    body: JSON.stringify({ category, priority }),
  });
}