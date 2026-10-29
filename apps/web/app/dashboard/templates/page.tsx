"use client";

/* WhatsApp templates: what Meta has approved, and why it matters.
 *
 * Templates are created and approved in WhatsApp Manager — this page mirrors
 * them. The send action lives in the conversation, where the consent basis and
 * the closed window are both visible.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  listWhatsAppTemplates,
  syncWhatsAppTemplates,
  type WhatsAppTemplate,
} from "@/lib/api-whatsapp-templates";

const STATUS_STYLE: Record<string, string> = {
  approved: "bg-emerald/10 text-emerald",
  pending: "bg-amber-100 text-amber-700 dark:bg-amber-400/10 dark:text-amber-300",
  rejected: "bg-[#FF4F6E]/10 text-[#C4304B] dark:text-[#FF8FA3]",
  paused: "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50",
  disabled: "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50",
  draft: "bg-ink/[0.06] text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50",
};

function StatusChip({ status }: { status: string }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
        STATUS_STYLE[status] ?? STATUS_STYLE.draft
      }`}
    >
      {status}
    </span>
  );
}

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "approved" | "utility">("all");

  const load = useCallback(async () => {
    try {
      setTemplates(await listWhatsAppTemplates());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load templates.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sync = async () => {
    setSyncing(true);
    setNotice(null);
    try {
      const result = await syncWhatsAppTemplates();
      setTemplates(result.templates);
      setNotice(
        `Synced ${result.created + result.updated} template${
          result.created + result.updated === 1 ? "" : "s"
        } from Meta.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sync from Meta.");
    } finally {
      setSyncing(false);
    }
  };

  const visible = useMemo(() => {
    if (filter === "approved") return templates.filter((t) => t.status === "approved");
    if (filter === "utility") return templates.filter((t) => t.category === "utility");
    return templates;
  }, [templates, filter]);

  const counts = useMemo(() => {
    return {
      approved: templates.filter((t) => t.status === "approved").length,
      pending: templates.filter((t) => t.status === "pending").length,
      utility: templates.filter(
        (t) => t.category === "utility" && t.status === "approved",
      ).length,
    };
  }, [templates]);

  return (
    <div className="h-full overflow-y-auto bg-[#f1f2f5] dark:bg-[#0f0b18]">
      <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6">
        <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-ink/40 dark:text-fog/40">
              WhatsApp
            </p>
            <h1 className="mt-1 text-[24px] font-semibold tracking-tight text-ink dark:text-fog">
              Message templates
            </h1>
            <p className="mt-1 max-w-2xl text-[13px] text-ink/50 dark:text-fog/50">
              Outside the 24-hour reply window WhatsApp only accepts an approved
              template. Create and submit them in WhatsApp Manager, then sync
              here — sending happens from the conversation.
            </p>
          </div>
          <button
            onClick={() => void sync()}
            disabled={syncing}
            className="rounded-full bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-[0_1px_0_rgba(255,255,255,0.2)_inset,0_6px_16px_-8px_rgba(61,29,110,0.7)] transition active:translate-y-[2px] active:scale-[0.98] disabled:opacity-50"
          >
            {syncing ? "Syncing…" : "Sync from Meta"}
          </button>
        </header>

        {error && (
          <p
            role="alert"
            className="mb-4 rounded-2xl bg-[#FF4F6E]/10 px-4 py-3 text-[12px] font-medium text-[#C4304B] dark:text-[#FF8FA3]"
          >
            {error}
          </p>
        )}
        {notice && (
          <p className="mb-4 rounded-2xl bg-emerald/10 px-4 py-3 text-[12px] font-medium text-emerald">
            {notice}
          </p>
        )}

        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          {[
            { label: "Approved", value: counts.approved },
            { label: "Awaiting review", value: counts.pending },
            { label: "Approved utility", value: counts.utility },
          ].map((card) => (
            <div
              key={card.label}
              className="rounded-[24px] border border-ink/[0.06] bg-white px-4 py-3 shadow-[0_1px_2px_rgba(20,16,31,0.04),0_12px_26px_-20px_rgba(20,16,31,0.3)] dark:border-fog/[0.08] dark:bg-ink"
            >
              <p className="text-[10px] font-bold uppercase tracking-widest text-ink/40 dark:text-fog/40">
                {card.label}
              </p>
              <p className="mt-1 text-[20px] font-semibold text-ink dark:text-fog">
                {card.value}
              </p>
            </div>
          ))}
        </div>

        <section className="rounded-[28px] border border-ink/[0.06] bg-white shadow-[0_1px_2px_rgba(20,16,31,0.04),0_14px_30px_-22px_rgba(20,16,31,0.3)] dark:border-fog/[0.08] dark:bg-ink">
          <div className="flex flex-wrap items-center gap-2 border-b border-ink/[0.06] px-5 py-3 dark:border-fog/[0.08]">
            {(["all", "approved", "utility"] as const).map((key) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                aria-pressed={filter === key}
                className={`rounded-full px-3 py-1 text-[11px] font-semibold capitalize transition ${
                  filter === key
                    ? "bg-deep-violet text-white"
                    : "text-ink/45 hover:text-ink/70 dark:text-fog/45 dark:hover:text-fog/70"
                }`}
              >
                {key}
              </button>
            ))}
            <span className="ml-auto text-[11px] text-ink/40 dark:text-fog/40">
              {visible.length} shown
            </span>
          </div>

          {loading ? (
            <p className="px-5 py-10 text-center text-[12px] text-ink/40 dark:text-fog/40">
              Loading…
            </p>
          ) : visible.length === 0 ? (
            <div className="px-5 py-10 text-center">
              <p className="text-[13px] font-medium text-ink/60 dark:text-fog/60">
                {templates.length === 0
                  ? "No templates synced yet."
                  : "Nothing matches this filter."}
              </p>
              <p className="mx-auto mt-1 max-w-md text-[12px] text-ink/40 dark:text-fog/40">
                {templates.length === 0
                  ? "Create a utility template in WhatsApp Manager (for example an appointment reminder), wait for approval, then press Sync from Meta."
                  : "Try the All filter."}
              </p>
            </div>
          ) : (
            <ul className="divide-y divide-ink/[0.05] dark:divide-fog/[0.06]">
              {visible.map((t) => (
                <li key={t.id} className="px-5 py-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink dark:text-fog">
                      {t.name}
                    </p>
                    <span className="rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/50 dark:bg-fog/[0.08] dark:text-fog/50">
                      {t.category}
                    </span>
                    <span className="text-[11px] font-medium text-ink/40 dark:text-fog/40">
                      {t.language}
                    </span>
                    <StatusChip status={t.status} />
                  </div>
                  <p className="mt-1.5 whitespace-pre-line text-[12px] leading-5 text-ink/55 dark:text-fog/55">
                    {t.body || "No body returned by Meta yet."}
                  </p>
                  <p className="mt-1 text-[10.5px] text-ink/35 dark:text-fog/35">
                    {t.variables > 0
                      ? `${t.variables} variable${t.variables === 1 ? "" : "s"}`
                      : "No variables"}
                    {t.last_synced_at
                      ? ` · synced ${new Date(t.last_synced_at).toLocaleString()}`
                      : ""}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>

        <p className="mt-6 text-[11px] leading-5 text-ink/40 dark:text-fog/40">
          A template can only be sent to a customer with a recorded opt-in — the
          Instagram handoff records it automatically, and an operator can record
          it from the conversation. Marketing templates without consent are
          refused.
        </p>
      </div>
    </div>
  );
}
