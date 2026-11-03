import { adminFetch } from "@/lib/admin-api";
import { FLAT_NAV } from "@/lib/admin-nav";

export type SearchGroupKey =
  | "tenants"
  | "operators"
  | "models"
  | "plans"
  | "pricing"
  | "jobs"
  | "audit"
  | "pages";

export interface AdminSearchItem {
  id: string;
  group: SearchGroupKey;
  title: string;
  subtitle?: string;
  meta?: string;
  href: string;
}

export interface AdminSearchGroup {
  key: SearchGroupKey;
  label: string;
  items: AdminSearchItem[];
}

export interface AdminSearchResponse {
  query: string;
  groups: AdminSearchGroup[];
  total: number;
  /** True when the local example set answered because the API is not wired. */
  preview?: boolean;
}

export const SEARCH_GROUP_ORDER: SearchGroupKey[] = [
  "tenants",
  "operators",
  "models",
  "plans",
  "pricing",
  "jobs",
  "audit",
  "pages",
];

export const SEARCH_GROUP_LABELS: Record<SearchGroupKey, string> = {
  tenants: "Tenants",
  operators: "Operators",
  models: "Models",
  plans: "Plans",
  pricing: "Pricing",
  jobs: "Jobs",
  audit: "Audit log",
  pages: "Pages",
};

export const SEARCH_SCOPE = [
  { label: "Tenants", desc: "Email, name, listing, tenant ID", href: "/tenants" },
  { label: "Operators", desc: "Username, role, active state", href: "/operators" },
  { label: "Models", desc: "LLM, ASR, TTS provider/model IDs", href: "/llms" },
  { label: "Plans", desc: "Plan tiers and entitlements", href: "/plans" },
  { label: "Pricing", desc: "LLM and voice rates", href: "/pricing" },
  { label: "Jobs", desc: "Job ID, type, status, tenant", href: "/jobs" },
  { label: "Audit log", desc: "Actor, action, target", href: "/audit-log" },
];

const PREVIEW_ENABLED =
  process.env.NODE_ENV !== "production" ||
  process.env.NEXT_PUBLIC_ADMIN_SEARCH_PREVIEW === "true";

function result(
  group: SearchGroupKey,
  id: string,
  title: string,
  subtitle: string,
  href: string,
  meta?: string,
): AdminSearchItem {
  return { id, group, title, subtitle, href, meta };
}

const PAGE_ITEMS: AdminSearchItem[] = FLAT_NAV.filter(
  (item) => item.href !== "/search",
).map((item) =>
  result("pages", item.href, item.label, item.desc, item.href, item.section),
);

const PREVIEW_ITEMS: AdminSearchItem[] = [
  result(
    "tenants",
    "t-001",
    "Abdulrahman Manea",
    "tenant@example.com · Sayvors Coffee",
    "/tenants/t-001",
    "Pro",
  ),
  result(
    "tenants",
    "t-002",
    "Layla Hassan",
    "layla@example.com · Aster Beans",
    "/tenants/t-002",
    "Starter",
  ),
  result(
    "tenants",
    "t-003",
    "Omar Al-Harbi",
    "omar@example.com · Makkah Grill",
    "/tenants/t-003",
    "Growth",
  ),
  result(
    "tenants",
    "t-004",
    "Noura Saleh",
    "noura@example.com · Riyadh Dental",
    "/tenants/t-004",
    "Pro",
  ),

  result("operators", "op-1", "admin", "Owner · active", "/operators", "Owner"),
  result(
    "operators",
    "op-2",
    "sara.ops",
    "Operator · active",
    "/operators",
    "Operator",
  ),
  result(
    "operators",
    "op-3",
    "bilal.support",
    "Operator · disabled",
    "/operators",
    "Disabled",
  ),

  result(
    "models",
    "model-groq",
    "groq:oss-120b",
    "Groq · Llama 3.3 70B",
    "/llms",
    "LLM",
  ),
  result(
    "models",
    "model-openai",
    "openai:gpt-4o",
    "OpenAI · GPT-4o",
    "/llms",
    "LLM",
  ),
  result(
    "models",
    "model-google",
    "google:gemini-2.5-pro",
    "Google · Gemini 2.5 Pro",
    "/llms",
    "LLM",
  ),
  result(
    "models",
    "model-deepgram",
    "deepgram:nova-3",
    "Deepgram · speech-to-text",
    "/asr",
    "ASR",
  ),
  result(
    "models",
    "model-eleven",
    "elevenlabs:multilingual-v2",
    "ElevenLabs · voice replies",
    "/voice",
    "TTS",
  ),

  result("plans", "plan-pro", "Pro", "2,000 AI credits · all channels", "/plans", "$99/mo"),
  result("plans", "plan-growth", "Growth", "500 credits · WhatsApp + GBP", "/plans", "$39/mo"),
  result("plans", "plan-starter", "Starter", "100 credits · one listing", "/plans", "$19/mo"),

  result("pricing", "price-groq-in", "groq input", "15¢ / 1M tokens", "/pricing", "LLM input"),
  result("pricing", "price-groq-out", "groq output", "60¢ / 1M tokens", "/pricing", "LLM output"),
  result("pricing", "price-asr", "ASR minute", "1¢ / audio minute", "/pricing", "Voice"),
  result("pricing", "price-tts", "TTS 1k chars", "0¢ / 1k chars · free", "/pricing", "Voice"),

  result("jobs", "job-1", "review.sync", "tenant@example.com · running", "/jobs", "running"),
  result("jobs", "job-2", "post.publish", "omar@example.com · queued", "/jobs", "queued"),
  result("jobs", "job-3", "voice.transcribe", "layla@example.com · failed", "/jobs", "failed"),

  result("audit", "audit-1", "plan.changed", "admin → tenant@example.com", "/audit-log", "Pro"),
  result("audit", "audit-2", "pricing.updated", "admin → groq input", "/audit-log", "60¢"),
  result("audit", "audit-3", "operator.created", "admin → sara.ops", "/audit-log", "Operator"),

  ...PAGE_ITEMS,
];

function previewSearch(query: string): AdminSearchResponse {
  const needle = query.toLowerCase();
  const groups = SEARCH_GROUP_ORDER.map((key) => ({
    key,
    label: SEARCH_GROUP_LABELS[key],
    items: PREVIEW_ITEMS.filter(
      (item) =>
        item.group === key &&
        [item.title, item.subtitle, item.meta]
          .filter(Boolean)
          .some((value) => value!.toLowerCase().includes(needle)),
    ),
  })).filter((group) => group.items.length > 0);
  return {
    query,
    groups,
    total: groups.reduce((sum, group) => sum + group.items.length, 0),
    preview: true,
  };
}

export function quickLinksGroup(): AdminSearchGroup {
  return {
    key: "pages",
    label: "Quick links",
    items: PAGE_ITEMS.filter((item) => item.href !== "/search").slice(0, 6),
  };
}

/**
 * Search the admin console.
 *
 * Until the API endpoint lands, development falls back to a small, clearly
 * labelled example set so the UI can be reviewed. Production never shows the
 * examples: it surfaces the endpoint error instead.
 */
export async function searchAdmin(query: string): Promise<AdminSearchResponse> {
  const q = query.trim();
  if (!q) {
    return { query: "", groups: [], total: 0 };
  }
  try {
    return await adminFetch<AdminSearchResponse>(
      `/api/v1/admin/search?q=${encodeURIComponent(q)}`,
    );
  } catch (error) {
    if (!PREVIEW_ENABLED) throw error;
    if (
      error instanceof Error &&
      /session expired|unauthori[sz]ed|forbidden|401|403/i.test(error.message)
    ) {
      throw error;
    }
    return previewSearch(q);
  }
}
