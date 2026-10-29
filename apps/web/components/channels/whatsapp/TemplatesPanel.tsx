"use client";

/* Templates tab inside the WhatsApp hub.
 *
 * Mirrors what Meta has approved; sending happens from the conversation,
 * where the consent basis and the closed window are visible.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  listWhatsAppTemplates,
  syncWhatsAppTemplates,
  type WhatsAppTemplate,
} from "@/lib/api-whatsapp-templates";

const CARD =
  "rounded-lg bg-[var(--wa-panel)] shadow-[0_1px_2px_rgba(0,0,0,0.12)]";
const MUTED = "text-[12px] text-[var(--wa-text-2)]";

const STATUS_STYLE: Record<string, string> = {
  approved: "bg-[var(--wa-accent)]/12 text-[var(--wa-accent-deep)]",
  pending: "bg-amber-100 text-amber-700",
  rejected: "bg-[#FF4F6E]/10 text-[#C4304B]",
};

function StatusChip({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${STATUS_STYLE[status] ?? "bg-[var(--wa-panel-2)] text-[var(--wa-text-3)]"}`}>
      {status}
    </span>
  );
}

export default function TemplatesPanel() {
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

  const counts = useMemo(() => ({
    approved: templates.filter((t) => t.status === "approved").length,
    pending: templates.filter((t) => t.status === "pending").length,
    utility: templates.filter((t) => t.category === "utility" && t.status === "approved").length,
  }), [templates]);

  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="rounded-lg bg-[var(--wa-warn-bg)] px-3 py-2 text-[12px] text-[var(--wa-warn-text)]">
          {error}
        </p>
      )}
      {notice && (
        <p className="rounded-lg bg-[var(--wa-accent)]/10 px-3 py-2 text-[12px] font-medium text-[var(--wa-accent-deep)]">
          {notice}
        </p>
      )}

      <div className="grid gap-2.5 sm:grid-cols-3">
        {[
          { label: "Approved", value: counts.approved },
          { label: "Awaiting review", value: counts.pending },
          { label: "Approved utility", value: counts.utility },
        ].map((card) => (
          <div key={card.label} className={`${CARD} px-4 py-3`}>
            <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--wa-text-3)]">
              {card.label}
            </p>
            <p className="mt-0.5 text-[20px] font-semibold text-[var(--wa-text)]">
              {card.value}
            </p>
          </div>
        ))}
      </div>

      <section className={CARD}>
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--wa-border)] px-4 py-2.5">
          {(["all", "approved", "utility"] as const).map((key) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              aria-pressed={filter === key}
              className={`rounded-full px-3 py-1 text-[11px] font-semibold capitalize transition ${
                filter === key
                  ? "bg-[var(--wa-accent)] text-white"
                  : "text-[var(--wa-text-2)] hover:text-[var(--wa-text)]"
              }`}
            >
              {key}
            </button>
          ))}
          <span className="ml-auto text-[11px] text-[var(--wa-text-3)]">
            {visible.length} shown
          </span>
          <button
            onClick={() => void sync()}
            disabled={syncing}
            className="rounded-full bg-[var(--wa-accent)] px-3 py-1 text-[11px] font-bold text-white disabled:opacity-50"
          >
            {syncing ? "Syncing…" : "Sync from Meta"}
          </button>
        </div>

        {loading ? (
          <p className="px-4 py-8 text-center text-[12px] text-[var(--wa-text-3)]">Loading…</p>
        ) : visible.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <p className="text-[13px] font-medium text-[var(--wa-text-2)]">
              {templates.length === 0 ? "No templates synced yet." : "Nothing matches this filter."}
            </p>
            <p className={`mx-auto mt-1 max-w-md ${MUTED}`}>
              {templates.length === 0
                ? "Create a utility template in WhatsApp Manager (for example an order update), wait for approval, then press Sync from Meta."
                : "Try the All filter."}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--wa-border)]">
            {visible.map((t) => (
              <li key={t.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="min-w-0 flex-1 truncate text-[13px] font-semibold text-[var(--wa-text)]">
                    {t.name}
                  </p>
                  <span className="rounded-full bg-[var(--wa-panel-2)] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-[var(--wa-text-3)]">
                    {t.category}
                  </span>
                  <span className="text-[11px] font-medium text-[var(--wa-text-3)]">
                    {t.language}
                  </span>
                  <StatusChip status={t.status} />
                </div>
                <p className="mt-1 whitespace-pre-line text-[12px] leading-5 text-[var(--wa-text-2)]">
                  {t.body || "No body returned by Meta yet."}
                </p>
                <p className="mt-0.5 text-[10.5px] text-[var(--wa-text-3)]">
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

      <p className="px-1 text-[11px] leading-5 text-[var(--wa-text-3)]">
        Outside the 24-hour window only an approved template can be sent. A
        customer needs a recorded opt-in — the Instagram handoff records it
        automatically, and an operator can record it from the conversation.
      </p>
    </div>
  );
}
