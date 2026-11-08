"use client";

import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type SyntheticEvent,
} from "react";

import {
  cancelEmailCampaign,
  createEmailCampaign,
  fetchCampaignAudience,
  fetchCampaignRecipients,
  fetchEmailCampaigns,
  startEmailCampaign,
  type CampaignAudience,
  type CampaignAudienceItem,
  type CampaignRecipient,
  type EmailCampaign,
} from "@/lib/admin-api";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

function statusStyle(status: EmailCampaign["status"]): {
  pill: string;
  label: string;
} {
  switch (status) {
    case "running":
      return { pill: "bg-sky-50 text-sky-700 ring-1 ring-sky-200", label: "Running" };
    case "completed":
      return {
        pill: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
        label: "Completed",
      };
    case "cancelled":
      return {
        pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200",
        label: "Cancelled",
      };
    default:
      return { pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200", label: "Draft" };
  }
}

function fmtDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function AudienceTable({ audience }: { audience: CampaignAudience | null }) {
  const [items, setItems] = useState<CampaignAudienceItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loadedPages = useRef(0);

  useEffect(() => {
    if (audience && loadedPages.current === 0) {
      setItems(audience.items);
    }
  }, [audience]);

  const loadMore = async () => {
    if (!audience) return;
    setLoading(true);
    setError(null);
    try {
      const next = await fetchCampaignAudience(50, items.length);
      setItems((prev) => [...prev, ...next.items]);
      loadedPages.current += 1;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the audience.");
    } finally {
      setLoading(false);
    }
  };

  const total = audience?.eligible ?? 0;

  return (
    <details className="panel p-4">
      <summary className="cursor-pointer select-none text-[14px] font-bold text-ink">
        Who is eligible ({total.toLocaleString()})
        <span className="ml-2 text-[10.5px] font-normal text-ink/40">
          verified emails with newsletter consent
        </span>
      </summary>
      <p className="mt-2 text-[11px] text-ink/45">
        These are the addresses the next campaign snapshots and receives. Suppressed
        addresses are counted but skipped at enqueue time.
      </p>
      {error && (
        <p className="mt-2 rounded-[2px] bg-red-50 px-2 py-1 text-[11px] text-red-700">{error}</p>
      )}
      {items.length === 0 ? (
        <p className="mt-3 text-[12px] text-ink/45">No eligible recipients yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-[11.5px]">
            <thead>
              <tr className="border-b border-[var(--ui-line)] text-[10px] uppercase tracking-[0.08em] text-ink/40">
                <th className="py-1.5 pr-3 font-bold">Email</th>
                <th className="py-1.5 pr-3 font-bold">Name</th>
                <th className="py-1.5 font-bold">Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id} className="border-b border-[var(--ui-line)]/60 last:border-0">
                  <td className="py-1.5 pr-3 font-mono text-[11px] text-ink">
                    {item.email ? (
                      <Link
                        href={`/tenants/${item.tenant_id}`}
                        className="hover:underline"
                        title="Open tenant"
                      >
                        {item.email}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="py-1.5 pr-3 text-ink/65">{item.first_name || "—"}</td>
                  <td className="py-1.5">
                    {item.suppressed ? (
                      <span className="rounded-full bg-red-50 px-1.5 py-0.5 text-[10px] font-bold text-red-700">
                        suppressed
                      </span>
                    ) : (
                      <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-700">
                        eligible
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {items.length < total && (
        <button
          type="button"
          onClick={() => void loadMore()}
          disabled={loading}
          className={`mt-2 h-8 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 text-[11px] font-semibold text-ink disabled:opacity-50 ${FOCUS}`}
        >
          {loading ? "Loading…" : `Load more (${items.length} / ${total.toLocaleString()})`}
        </button>
      )}
    </details>
  );
}

const RECIPIENT_FILTERS = [
  { value: "", label: "All" },
  { value: "queued", label: "Queued" },
  { value: "sent", label: "Sent" },
  { value: "failed", label: "Failed" },
  { value: "dead", label: "Dead" },
  { value: "cancelled", label: "Cancelled" },
];

function CampaignRecipientsTable({ campaign }: { campaign: EmailCampaign }) {
  const [items, setItems] = useState<CampaignRecipient[]>([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (nextStatus: string, offset: number, replace: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchCampaignRecipients(
        campaign.id,
        nextStatus || undefined,
        50,
        offset,
      );
      setItems((prev) => (replace ? data.items : [...prev, ...data.items]));
      setTotal(data.total);
      setCounts(data.counts);
      setLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load recipients.");
    } finally {
      setLoading(false);
    }
  };

  const onToggle = (event: SyntheticEvent<HTMLDetailsElement>) => {
    if (event.currentTarget.open && !loaded) {
      void load(status, 0, true);
    }
  };

  return (
    <details className="mt-3 border-t border-[var(--ui-line)] pt-2" onToggle={onToggle}>
      <summary className="cursor-pointer select-none text-[11px] font-bold text-ink/60">
        Recipients · {campaign.sent.toLocaleString()} sent ·{" "}
        <span className={campaign.failed + campaign.dead > 0 ? "text-red-600" : ""}>
          {campaign.failed.toLocaleString()} failed
        </span>
      </summary>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {RECIPIENT_FILTERS.map((filter) => (
          <button
            key={filter.value || "all"}
            type="button"
            onClick={() => {
              setStatus(filter.value);
              void load(filter.value, 0, true);
            }}
            className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${
              status === filter.value
                ? "bg-deep-violet text-white"
                : "border border-[var(--ui-line)] bg-[var(--ui-surface)] text-ink/55"
            } ${FOCUS}`}
          >
            {filter.label}
            {filter.value && counts[filter.value] !== undefined
              ? ` ${counts[filter.value].toLocaleString()}`
              : ""}
          </button>
        ))}
      </div>

      {error && (
        <p className="mt-2 rounded-[2px] bg-red-50 px-2 py-1 text-[11px] text-red-700">{error}</p>
      )}
      {!loading && items.length === 0 && loaded ? (
        <p className="mt-2 text-[11px] text-ink/45">No recipients in this filter.</p>
      ) : (
        items.length > 0 && (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr className="border-b border-[var(--ui-line)] text-[10px] uppercase tracking-[0.08em] text-ink/40">
                  <th className="py-1.5 pr-3 font-bold">Email</th>
                  <th className="py-1.5 pr-3 font-bold">Outbox</th>
                  <th className="py-1.5 pr-3 font-bold">Delivery</th>
                  <th className="py-1.5 pr-3 font-bold">Tries</th>
                  <th className="py-1.5 font-bold">Error</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b border-[var(--ui-line)]/60 last:border-0">
                    <td className="py-1.5 pr-3 font-mono text-[10.5px] text-ink">
                      {item.tenant_id ? (
                        <Link
                          href={`/tenants/${item.tenant_id}`}
                          className="hover:underline"
                          title="Open tenant"
                        >
                          {item.email}
                        </Link>
                      ) : (
                        item.email
                      )}
                    </td>
                    <td className="py-1.5 pr-3">
                      <span
                        className={`rounded-full px-1.5 py-0.5 text-[9.5px] font-bold ${
                          item.status === "sent"
                            ? "bg-emerald-50 text-emerald-700"
                            : item.status === "failed" || item.status === "dead"
                              ? "bg-red-50 text-red-700"
                              : item.status === "cancelled"
                                ? "bg-ink/5 text-ink/55"
                                : "bg-amber-50 text-amber-700"
                        }`}
                      >
                        {item.status}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3">
                      {item.last_event ? (
                        <span
                          title={item.last_event_detail || ""}
                          className={`rounded-full px-1.5 py-0.5 text-[9.5px] font-bold ${
                            item.last_event === "delivered"
                              ? "bg-emerald-50 text-emerald-700"
                              : item.last_event === "bounced" ||
                                  item.last_event === "complained"
                                ? "bg-red-50 text-red-700"
                                : "bg-ink/5 text-ink/55"
                          }`}
                        >
                          {item.last_event}
                        </span>
                      ) : (
                        <span className="text-ink/30">—</span>
                      )}
                    </td>
                    <td className="py-1.5 pr-3 tabular-nums text-ink/55">{item.attempts}</td>
                    <td className="max-w-[22rem] truncate py-1.5 text-red-600" title={item.error || ""}>
                      {item.error || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {items.length < total && (
        <button
          type="button"
          onClick={() => void load(status, items.length, false)}
          disabled={loading}
          className={`mt-2 h-8 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 text-[11px] font-semibold text-ink disabled:opacity-50 ${FOCUS}`}
        >
          {loading ? "Loading…" : `Load more (${items.length} / ${total.toLocaleString()})`}
        </button>
      )}
    </details>
  );
}

export default function EmailCampaignsPage() {
  const [campaigns, setCampaigns] = useState<EmailCampaign[]>([]);
  const [audience, setAudience] = useState<CampaignAudience | null>(null);
  const [subject, setSubject] = useState("");
  const [html, setHtml] = useState(
    '<p dir="ltr">Hi {name},</p>\n<p dir="ltr">Here is what is new at Sayvors.</p>',
  );
  const [text, setText] = useState("");
  const [batchSize, setBatchSize] = useState(500);
  const [intervalSeconds, setIntervalSeconds] = useState(60);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [list, size] = await Promise.all([
        fetchEmailCampaigns(),
        fetchCampaignAudience(),
      ]);
      setCampaigns(list.items);
      setAudience(size);
      setError(null);
      setUpdatedAt(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load campaigns.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const first = window.setTimeout(() => void refresh(), 0);
    const tick = () => {
      if (!document.hidden) void refresh();
    };
    const onVisibility = () => {
      if (!document.hidden) void refresh();
    };
    timer.current = setInterval(tick, 10000);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearTimeout(first);
      document.removeEventListener("visibilitychange", onVisibility);
      if (timer.current) clearInterval(timer.current);
    };
  }, [refresh]);

  const create = async () => {
    if (!subject.trim() || !html.trim()) {
      setError("Subject and body are required.");
      return;
    }
    if (batchSize < 50 || batchSize > 2000) {
      setError("Batch size must be between 50 and 2000 recipients.");
      return;
    }
    if (intervalSeconds < 10 || intervalSeconds > 3600) {
      setError("Interval must be between 10 and 3600 seconds.");
      return;
    }
    setBusy("create");
    setError(null);
    setNotice(null);
    try {
      const campaign = await createEmailCampaign({
        subject: subject.trim(),
        html,
        text: text.trim() || null,
        batch_size: batchSize,
        interval_seconds: intervalSeconds,
      });
      setNotice(`Draft created: ${campaign.subject}. Review it, then press Start.`);
      setSubject("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the campaign.");
    } finally {
      setBusy(null);
    }
  };

  const start = async (campaign: EmailCampaign) => {
    setBusy(campaign.id);
    setError(null);
    setNotice(null);
    try {
      await startEmailCampaign(campaign.id);
      setNotice(`Started "${campaign.subject}". The worker expands it in batches.`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the campaign.");
    } finally {
      setBusy(null);
    }
  };

  const cancel = async (campaign: EmailCampaign) => {
    setBusy(campaign.id);
    setError(null);
    setNotice(null);
    try {
      await cancelEmailCampaign(campaign.id);
      setNotice(`Cancelled "${campaign.subject}". Already-queued emails still deliver.`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not cancel the campaign.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-[18px] font-bold tracking-tight text-ink">Email campaigns</h1>
          <p className="mt-0.5 text-[12px] text-ink/45">
            Compose a newsletter once. The worker expands it into the durable outbox
            in paced batches; suppression and unsubscribe are enforced per recipient.
          </p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-ink/40">
          {audience && (
            <span className="rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 py-1.5 font-semibold text-ink/65">
              {audience.eligible.toLocaleString()} eligible · cap{" "}
              {audience.max_recipients.toLocaleString()}
            </span>
          )}
          <button
            type="button"
            onClick={() => void refresh()}
            className={`h-9 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 text-[12px] font-semibold text-ink ${FOCUS}`}
          >
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-[2px] border border-red-200 bg-red-50 p-3 text-[12px] text-red-800">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-[2px] border border-sky-200 bg-sky-50 p-3 text-[12px] text-sky-800">
          {notice}
        </div>
      )}

      <section className="panel p-4">
        <h2 className="text-[14px] font-bold text-ink">Composer</h2>
        <p className="mt-0.5 text-[11px] text-ink/45">
          Body is HTML. <code>{"{name}"}</code> and <code>{"{email}"}</code> are replaced
          per recipient. New links carry one-click unsubscribe headers.
        </p>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <label className="block">
            <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
              Subject
            </span>
            <input
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              maxLength={200}
              placeholder="What's new at Sayvors this week"
              className="mt-1 h-9 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] text-ink"
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
                Batch size (max per pass)
              </span>
              <input
                type="number"
                min={50}
                max={2000}
                value={batchSize}
                onChange={(e) => setBatchSize(Number(e.target.value) || 500)}
                onBlur={() =>
                  setBatchSize((value) => Math.min(2000, Math.max(50, value || 500)))
                }
                className="mt-1 h-9 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] text-ink"
              />
              <span className="mt-1 block text-[10px] text-ink/35">
                Up to 2,000 per pass; a smaller audience finishes in one pass
              </span>
            </label>
            <label className="block">
              <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
                Interval (s)
              </span>
              <input
                type="number"
                min={10}
                max={3600}
                value={intervalSeconds}
                onChange={(e) => setIntervalSeconds(Number(e.target.value) || 60)}
                onBlur={() =>
                  setIntervalSeconds((value) => Math.min(3600, Math.max(10, value || 60)))
                }
                className="mt-1 h-9 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] text-ink"
              />
              <span className="mt-1 block text-[10px] text-ink/35">
                10–3,600 seconds between passes
              </span>
            </label>
          </div>
        </div>

        <label className="mt-3 block">
          <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
            HTML body
          </span>
          <textarea
            value={html}
            onChange={(e) => setHtml(e.target.value)}
            rows={8}
            spellCheck={false}
            className="mt-1 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-2 font-mono text-[11.5px] leading-relaxed text-ink"
          />
        </label>
        <label className="mt-3 block">
          <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
            Plain-text fallback <span className="normal-case tracking-normal text-ink/30">(optional)</span>
          </span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            className="mt-1 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-2 text-[11.5px] leading-relaxed text-ink"
          />
        </label>

        <div className="mt-3 flex items-center gap-2">
          <button
            type="button"
            onClick={() => void create()}
            disabled={busy === "create"}
            className={`h-9 rounded-[2px] bg-deep-violet px-3 text-[12px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
          >
            {busy === "create" ? "Creating…" : "Create draft"}
          </button>
          <span className="text-[10.5px] text-ink/40">
            A draft does not send anything. Start sends it to the snapshot of eligible
            recipients.
          </span>
        </div>
      </section>

      <AudienceTable audience={audience} />

      <section className="panel p-4">
        <div className="flex items-baseline justify-between">
          <h2 className="text-[14px] font-bold text-ink">Campaigns</h2>
          <span className="text-[10.5px] text-ink/40">
            {loading ? "Loading…" : `${campaigns.length} total`}
          </span>
        </div>

        {!loading && campaigns.length === 0 ? (
          <p className="mt-3 text-[12px] text-ink/45">
            No campaigns yet. Create a draft above.
          </p>
        ) : (
          <div className="mt-3 space-y-3">
            {campaigns.map((campaign) => {
              const status = statusStyle(campaign.status);
              const total = Math.max(1, campaign.total_recipients);
              const percent = Math.min(
                100,
                Math.round((campaign.expanded_recipients / total) * 100),
              );
              const canStart = campaign.status === "draft";
              const canCancel =
                campaign.status === "draft" || campaign.status === "running";
              return (
                <article
                  key={campaign.id}
                  className="rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-3"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="truncate text-[12.5px] font-bold text-ink">
                          {campaign.subject}
                        </h3>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${status.pill}`}>
                          {status.label}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[10.5px] text-ink/40">
                        Created {fmtDate(campaign.created_at)} by{" "}
                        {campaign.created_by || "—"} · {campaign.batch_size}/batch every{" "}
                        {campaign.interval_seconds}s
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {canStart && (
                        <button
                          type="button"
                          onClick={() => void start(campaign)}
                          disabled={busy === campaign.id}
                          className={`h-8 rounded-[2px] bg-deep-violet px-2.5 text-[11px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
                        >
                          Start
                        </button>
                      )}
                      {canCancel && (
                        <button
                          type="button"
                          onClick={() => void cancel(campaign)}
                          disabled={busy === campaign.id}
                          className={`h-8 rounded-[2px] border border-red-200 bg-red-50 px-2.5 text-[11px] font-semibold text-red-700 hover:bg-red-100 disabled:opacity-50 ${FOCUS}`}
                        >
                          Cancel
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="mt-3 flex items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--ui-sunken)]">
                      <div
                        className="h-full rounded-full bg-deep-violet"
                        style={{ width: `${percent}%` }}
                      />
                    </div>
                    <span className="w-28 text-right text-[10.5px] tabular-nums text-ink/50">
                      {campaign.expanded_recipients.toLocaleString()} /{" "}
                      {campaign.total_recipients.toLocaleString()} expanded
                    </span>
                  </div>

                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10.5px] text-ink/50">
                    <span>queued {campaign.queued.toLocaleString()}</span>
                    <span>sent {campaign.sent.toLocaleString()}</span>
                    <span className={campaign.failed ? "text-red-600" : ""}>
                      failed {campaign.failed.toLocaleString()}
                    </span>
                    <span className={campaign.dead ? "text-red-600" : ""}>
                      dead {campaign.dead.toLocaleString()}
                    </span>
                    {campaign.cancelled > 0 && (
                      <span>cancelled {campaign.cancelled.toLocaleString()}</span>
                    )}
                    {campaign.status === "completed" && (
                      <span>completed {fmtDate(campaign.completed_at)}</span>
                    )}
                  </div>
                  {campaign.error && (
                    <p className="mt-2 rounded-[2px] bg-red-50 px-2 py-1 text-[10.5px] text-red-700">
                      {campaign.error}
                    </p>
                  )}

                  <CampaignRecipientsTable campaign={campaign} />
                </article>
              );
            })}
          </div>
        )}

        {updatedAt && (
          <p className="mt-3 text-[10.5px] text-ink/35">
            Updated {updatedAt.toLocaleTimeString()} · auto-refreshes every 10s
          </p>
        )}
      </section>
    </div>
  );
}
