"use client";

import React, { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api-rag";

interface Channel {
  id: string;
  display_name: string | null;
  platform: string;
  status: string;
}

interface PipelineResult {
  review_id: string;
  issue_id: string | null;
  issue_created: boolean;
  skipped_reason: string | null;
  classification_error: string | null;
  ticket_number: string | null;
  handoff_code: string | null;
  handoff_eligible: boolean;
  handoff_link: string | null;
  sales_link: string | null;
  reply_preview: string | null;
  reply_error: string | null;
  published: boolean;
  status: string | null;
  primary_category: string | null;
  subcategory: string | null;
  subcategory_detail: string | null;
  intent: string | null;
  sentiment: string | null;
  priority: string | null;
  needs_attention: boolean | null;
  summary: string | null;
}

export default function ReviewPipelineTester() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState("");
  const [rating, setRating] = useState(1);
  const [reviewerName, setReviewerName] = useState("");
  const [reviewText, setReviewText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PipelineResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = (await apiFetch("/api/v1/channels?limit=100")) as { channels?: Channel[] };
        if (cancelled) return;
        const reviewChannels = (data?.channels ?? []).filter((channel) => channel.platform === "google_reviews");
        setChannels(reviewChannels);
        if (reviewChannels.length > 0) {
          setChannelId(reviewChannels[0].id);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Could not load channels.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!channelId || !reviewText.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const data = (await apiFetch(`/api/v1/channels/${channelId}/test-review`, {
        method: "POST",
        body: JSON.stringify({
          rating,
          review_text: reviewText.trim(),
          reviewer_name: reviewerName.trim() || null,
        }),
      })) as PipelineResult;
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The pipeline test did not finish.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-[2px] border border-ink/[0.08] bg-white p-4 shadow-sm">
      <h2 className="text-[14px] font-bold text-ink">Review pipeline test</h2>
      <p className="mt-0.5 max-w-3xl text-[12px] leading-relaxed text-ink/55">
        Run classification, ticketing, handoff, and the public reply preview. This does not fetch
        from Google, publish anything, or message the customer. The preview shows exactly what
        the reviewer would receive, including the WhatsApp handoff link.
      </p>

      {channels.length === 0 ? (
        <p className="mt-3 text-[12px] text-ink/55">
          Connect a Google reviews channel before testing the pipeline.
        </p>
      ) : (
        <form onSubmit={submit} className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-[12px] font-semibold text-ink/70">
              Google channel
              <select
                value={channelId}
                onChange={(event) => setChannelId(event.target.value)}
                className="mt-1 w-full rounded-[2px] border border-ink/15 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/50"
              >
                {channels.map((channel) => (
                  <option key={channel.id} value={channel.id}>
                    {channel.display_name || "Google location"}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[12px] font-semibold text-ink/70">
              Rating
              <select
                value={rating}
                onChange={(event) => setRating(Number(event.target.value))}
                className="mt-1 w-full rounded-[2px] border border-ink/15 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/50"
              >
                {[1, 2, 3, 4, 5].map((value) => (
                  <option key={value} value={value}>
                    {value} star{value === 1 ? "" : "s"}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block text-[12px] font-semibold text-ink/70">
            Reviewer name (optional)
            <input
              value={reviewerName}
              onChange={(event) => setReviewerName(event.target.value)}
              className="mt-1 w-full rounded-[2px] border border-ink/15 bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-deep-violet/50"
              placeholder="Example customer"
            />
          </label>

          <label className="block text-[12px] font-semibold text-ink/70">
            Review text
            <textarea
              value={reviewText}
              onChange={(event) => setReviewText(event.target.value)}
              rows={4}
              required
              className="mt-1 w-full rounded-[2px] border border-ink/15 bg-white px-3 py-2 text-[13px] leading-relaxed text-ink outline-none focus:border-deep-violet/50"
              placeholder="The restroom was dirty, staff did not help, and I want a refund."
            />
          </label>

          <button
            type="submit"
            disabled={busy || !reviewText.trim() || !channelId}
            className="rounded-[2px] bg-deep-violet px-4 py-2.5 text-[12px] font-bold text-white shadow-sm shadow-deep-violet/20 outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 disabled:opacity-50"
          >
            {busy ? "Running pipeline…" : "Run review pipeline"}
          </button>
        </form>
      )}

      {error && (
        <p className="mt-3 rounded-[2px] bg-coral/10 px-3 py-2 text-[12px] font-medium text-coral">
          {error}
        </p>
      )}

      {result && (
        <div className="mt-4 space-y-2 rounded-[2px] border border-ink/[0.06] bg-white p-3">
          <h3 className="text-[12px] font-bold text-ink">Pipeline result</h3>
          <dl className="grid gap-2 text-[12px] sm:grid-cols-2">
            <div>
              <dt className="text-ink/45">Issue created</dt>
              <dd className="font-semibold text-ink">{result.issue_created ? "Yes" : "No"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Status</dt>
              <dd className="font-semibold text-ink">{result.status ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Ticket</dt>
              <dd className="font-semibold text-deep-violet">{result.ticket_number ?? "No ticket"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Handoff code</dt>
              <dd className="font-semibold text-ink">{result.handoff_code ?? "None"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Category</dt>
              <dd className="font-semibold text-ink">{result.primary_category ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Subcategory</dt>
              <dd className="font-semibold text-ink">{result.subcategory ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Intent</dt>
              <dd className="font-semibold text-ink">{result.intent ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Sentiment</dt>
              <dd className="font-semibold text-ink">{result.sentiment ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Priority</dt>
              <dd className="font-semibold text-ink">{result.priority ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink/45">Needs attention</dt>
              <dd className="font-semibold text-ink">{String(result.needs_attention ?? false)}</dd>
            </div>
          </dl>

          <div className="rounded-[2px] border border-ink/[0.06] bg-ink/[0.02] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-[11px] font-bold uppercase tracking-[0.1em] text-ink/45">
                Public review reply preview
              </h4>
              <span className="rounded-[2px] bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800">
                Not published
              </span>
            </div>
            {result.reply_preview ? (
              <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-ink">
                {result.reply_preview}
              </p>
            ) : (
              <p className="mt-2 text-[12px] text-ink/50">No reply preview was generated.</p>
            )}
            {result.handoff_link ? (
              <a
                href={result.handoff_link}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-[12px] font-bold text-deep-violet underline underline-offset-2"
              >
                Open the reviewer WhatsApp handoff
              </a>
            ) : result.sales_link ? (
              <a
                href={result.sales_link}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-[12px] font-bold text-deep-violet underline underline-offset-2"
              >
                Open the WhatsApp sales conversation
              </a>
            ) : null}
          </div>

          {result.reply_error && (
            <p className="text-[12px] font-medium text-coral">
              Reply generation error: {result.reply_error}
            </p>
          )}
          {result.summary && (
            <p className="text-[12px] text-ink/70">
              <span className="font-semibold text-ink">Summary:</span> {result.summary}
            </p>
          )}
          {result.skipped_reason && (
            <p className="text-[12px] font-medium text-amber-700">
              Skipped: {result.skipped_reason}
            </p>
          )}
          {result.classification_error && (
            <p className="text-[12px] font-medium text-coral">
              Classification error: {result.classification_error}
            </p>
          )}
        </div>
      )}
    </section>
  );
}