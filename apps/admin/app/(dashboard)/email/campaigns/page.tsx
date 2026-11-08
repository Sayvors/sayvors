"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelEmailCampaign,
  createEmailCampaign,
  fetchCampaignAudience,
  fetchEmailCampaigns,
  startEmailCampaign,
  type CampaignAudience,
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
      return { pill: "bg-ink/5 text-ink/55 ring-1 ring-[var(--ui-line)]", label: "Cancelled" };
    default:
      return { pill: "bg-amber-50 text-amber-700 ring-1 ring-amber-200", label: "Draft" };
  }
}

function fmtDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
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
                          className={`h-8 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2.5 text-[11px] font-semibold text-ink disabled:opacity-50 ${FOCUS}`}
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
                    {campaign.status === "completed" && (
                      <span>completed {fmtDate(campaign.completed_at)}</span>
                    )}
                  </div>
                  {campaign.error && (
                    <p className="mt-2 rounded-[2px] bg-red-50 px-2 py-1 text-[10.5px] text-red-700">
                      {campaign.error}
                    </p>
                  )}
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
