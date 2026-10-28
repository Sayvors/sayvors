"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  bulkReviewRequests,
  generateReviewTemplate,
} from "@/lib/api-analytics";
import { getEntitlements, type Entitlements } from "@/lib/api-billing";
import {
  extractContacts,
  guessColumns,
  parseCsv,
  type ColumnGuess,
  type ParsedCsv,
} from "@/lib/csv";

export default function BulkReviewRequests({
  channelId,
  onDone,
}: {
  channelId?: string | null;
  onDone?: () => void;
}) {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [parsed, setParsed] = useState<ParsedCsv | null>(null);
  const [mapping, setMapping] = useState<ColumnGuess>({ email: null, phone: null, name: null, lastName: null });
  const [fileName, setFileName] = useState("");
  const [channel, setChannel] = useState<"email" | "whatsapp">("email");
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [mode, setMode] = useState<"now" | "batched">("batched");
  const [batchSize, setBatchSize] = useState(10);
  const [intervalMinutes, setIntervalMinutes] = useState(60);
  const [subject, setSubject] = useState("Would you leave us a quick review?");
  const [body, setBody] = useState(
    "Hi {name}, thanks for visiting! Would you mind leaving us a quick review? It really helps: {link}"
  );
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getEntitlements()
      .then((e) => { if (!cancelled) setEntitlements(e); })
      .catch(() => { /* quota stays unknown; the API still enforces it */ });
    return () => { cancelled = true; };
  }, []);

  const extraction = useMemo(
    () => (parsed ? extractContacts(parsed, mapping, channel) : { contacts: [], invalid: 0 }),
    [parsed, mapping, channel]
  );
  const valid = extraction.contacts;
  const invalidCount = extraction.invalid;
  const remaining = entitlements?.messages_remaining ?? null;
  const maxMessages = entitlements?.max_messages_per_month ?? null;
  const usedMessages = entitlements?.messages_used_this_month ?? 0;
  const quotaShort = channel === "whatsapp" && remaining !== null && valid.length > remaining;

  // First non-empty value in a column, for the "is this the right column?"
  // check next to each mapping dropdown.
  const sampleFor = (idx: number | null): string | null => {
    if (idx === null || !parsed) return null;
    for (const row of parsed.rows) {
      const v = (row[idx] ?? "").trim();
      if (v) return v.length > 42 ? `${v.slice(0, 42)}…` : v;
    }
    return null;
  };
  const missingContactColumn =
    channel === "email" ? mapping.email === null : mapping.phone === null;

  const onFile = async (file: File | null) => {
    if (!file) return;
    const text = await file.text();
    const p = parseCsv(text);
    setParsed(p);
    setMapping(guessColumns(p));
    setFileName(file.name);
    setMessage(null);
  };

  const writeWithAi = async () => {
    setAiBusy(true);
    setMessage(null);
    try {
      const t = await generateReviewTemplate({ channel, tone: "friendly" });
      setBody(t.body);
      if (channel === "email") setSubject(t.subject);
      setMessage(t.source === "ai" ? "Template drafted by AI. Review before sending." : "AI unavailable - a safe fallback template was used.");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not draft a template.");
    } finally {
      setAiBusy(false);
    }
  };

  const send = async () => {
    if (valid.length === 0) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await bulkReviewRequests({
        channel_id: channelId ?? null,
        channel,
        contacts: valid.map((r) => ({ email: r.email, phone: r.phone, name: r.name })),
        mode,
        batch_size: batchSize,
        interval_minutes: intervalMinutes,
        trigger: "campaign",
        subject: channel === "email" ? subject : null,
        body,
      });
      setMessage(
        `${res.queued} queued` +
          (res.sent_now ? ` · ${res.sent_now} sending now` : "") +
          (res.scheduled ? ` · ${res.scheduled} scheduled` : "") +
          (res.skipped ? ` · ${res.skipped} skipped (missing contact)` : "") +
          (res.skipped_quota ? ` · ${res.skipped_quota} skipped for plan quota` : "")
      );
      setParsed(null);
      setFileName("");
      if (fileRef.current) fileRef.current.value = "";
      onDone?.();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Bulk send failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.08] dark:bg-ink">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-[14px] font-bold text-ink dark:text-fog">Bulk review requests (CSV)</h3>
          <p className="mt-0.5 text-[11px] text-ink/50 dark:text-fog/50">
            Upload a CSV with email/phone and optional name. Send all at once or in timed batches.
          </p>
        </div>
        {valid.length > 0 && (
          <span className="rounded-full bg-deep-violet/10 px-2.5 py-1 text-[11px] font-bold text-deep-violet">
            {valid.length} ready
          </span>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => void onFile(e.target.files?.[0] ?? null)}
          className="block w-full max-w-xs rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink file:mr-3 file:rounded-lg file:border-0 file:bg-deep-violet/10 file:px-2.5 file:py-1 file:text-[11px] file:font-bold file:text-deep-violet dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
        />
        {fileName && <span className="text-[11px] text-ink/50 dark:text-fog/50">{fileName}</span>}
      </div>

      {parsed && (
        <div className="mt-3 rounded-xl border border-ink/[0.06] p-3 dark:border-fog/[0.08]">
          <p className="text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:text-fog/45">
            Column mapping · {parsed.headers.length} columns found
          </p>
          <p className="mt-0.5 text-[10px] text-ink/45 dark:text-fog/45">
            Only the mapped columns are read. Everything else in the sheet is ignored.
          </p>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            <label className="block">
              <span className="mb-1 block text-[10px] font-semibold text-ink/60 dark:text-fog/60">
                {channel === "email" ? "Email column" : "Phone / WhatsApp column"}
              </span>
              <select
                value={channel === "email" ? mapping.email ?? "" : mapping.phone ?? ""}
                onChange={(e) => {
                  const idx = e.target.value === "" ? null : Number(e.target.value);
                  setMapping((m) => (channel === "email" ? { ...m, email: idx } : { ...m, phone: idx }));
                }}
                className="w-full rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[11px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                <option value="">Not mapped</option>
                {parsed.headers.map((h, i) => <option key={i} value={i}>{h || `Column ${i + 1}`}</option>)}
              </select>
              <p className="mt-0.5 truncate text-[9px] text-ink/40 dark:text-fog/40">
                {sampleFor(channel === "email" ? mapping.email : mapping.phone) ?? "No sample value"}
              </p>
            </label>
            <label className="block">
              <span className="mb-1 block text-[10px] font-semibold text-ink/60 dark:text-fog/60">Name column (optional)</span>
              <select
                value={mapping.name ?? ""}
                onChange={(e) => setMapping((m) => ({ ...m, name: e.target.value === "" ? null : Number(e.target.value) }))}
                className="w-full rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[11px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                <option value="">Not mapped</option>
                {parsed.headers.map((h, i) => <option key={i} value={i}>{h || `Column ${i + 1}`}</option>)}
              </select>
              <p className="mt-0.5 truncate text-[9px] text-ink/40 dark:text-fog/40">
                {sampleFor(mapping.name) ?? "No sample value"}
              </p>
            </label>
            <label className="block">
              <span className="mb-1 block text-[10px] font-semibold text-ink/60 dark:text-fog/60">Last name (optional)</span>
              <select
                value={mapping.lastName ?? ""}
                onChange={(e) => setMapping((m) => ({ ...m, lastName: e.target.value === "" ? null : Number(e.target.value) }))}
                className="w-full rounded-lg border border-ink/[0.08] bg-white px-2 py-1.5 text-[11px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
              >
                <option value="">Not mapped</option>
                {parsed.headers.map((h, i) => <option key={i} value={i}>{h || `Column ${i + 1}`}</option>)}
              </select>
              <p className="mt-0.5 truncate text-[9px] text-ink/40 dark:text-fog/40">
                {sampleFor(mapping.lastName) ?? "No sample value"}
              </p>
            </label>
          </div>
          {missingContactColumn && (
            <p className="mt-2 text-[10px] font-semibold text-amber-700 dark:text-amber-400">
              No {channel === "email" ? "email" : "phone"} column detected. Pick the right column above - nothing will be sent until it is mapped.
            </p>
          )}
          {invalidCount > 0 && (
            <p className="mt-2 text-[10px] font-semibold text-amber-700 dark:text-amber-400">
              {invalidCount} row{invalidCount === 1 ? "" : "s"} skipped: the mapped {channel === "email" ? "email" : "phone"} cell is missing or invalid.
            </p>
          )}
        </div>
      )}

      {valid.length > 0 && (
        <div className="mt-3 max-h-28 overflow-y-auto rounded-xl border border-ink/[0.06] dark:border-fog/[0.08]">
          <table className="w-full text-left text-[11px]">
            <thead className="bg-ink/[0.03] text-[10px] uppercase tracking-wide text-ink/50 dark:bg-fog/[0.04] dark:text-fog/50">
              <tr>
                <th className="px-2 py-1.5">Contact</th>
                <th className="px-2 py-1.5">Name</th>
              </tr>
            </thead>
            <tbody>
              {valid.slice(0, 5).map((r, i) => (
                <tr key={i} className="border-t border-ink/[0.04] dark:border-fog/[0.06]">
                  <td className="px-2 py-1.5 text-ink dark:text-fog">{channel === "email" ? r.email : r.phone}</td>
                  <td className="px-2 py-1.5 text-ink/50 dark:text-fog/50">{r.name ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {valid.length > 5 && <p className="px-2 py-1 text-[10px] text-ink/40 dark:text-fog/40">+{valid.length - 5} more</p>}
        </div>
      )}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold text-ink/60 dark:text-fog/60">Channel</span>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as "email" | "whatsapp")}
            className="w-full rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
          >
            <option value="email">Email (Resend)</option>
            <option value="whatsapp">WhatsApp (Cloud API)</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold text-ink/60 dark:text-fog/60">Delivery</span>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as "now" | "batched")}
            className="w-full rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
          >
            <option value="batched">Scheduled in batches</option>
            <option value="now">Send all now</option>
          </select>
        </label>
      </div>

      {mode === "batched" && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold text-ink/60 dark:text-fog/60">Batch size</span>
            <input
              type="number"
              min={1}
              max={500}
              value={batchSize}
              onChange={(e) => setBatchSize(Math.max(1, Number(e.target.value) || 1))}
              className="w-full rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] font-semibold text-ink/60 dark:text-fog/60">Minutes between batches</span>
            <input
              type="number"
              min={1}
              max={10080}
              value={intervalMinutes}
              onChange={(e) => setIntervalMinutes(Math.max(1, Number(e.target.value) || 1))}
              className="w-full rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            />
          </label>
        </div>
      )}

      {channel === "whatsapp" && (
        <div className="mt-3 rounded-xl border border-amber-300/60 bg-amber-50 p-3 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p className="text-[11px] font-bold text-amber-800 dark:text-amber-300">
            24-hour window warning
          </p>
          <p className="mt-0.5 text-[10px] leading-relaxed text-amber-800/80 dark:text-amber-200/80">
            WhatsApp only allows free-form messages within 24 hours of the customer&apos;s last message.
            Contacts outside that window will be rejected by Meta and shown as <strong>failed</strong>.
            An approved WhatsApp template is required for cold sends - do not promise delivery until it is configured.
          </p>
        </div>
      )}

      {channel === "whatsapp" && entitlements && (
        <div className="mt-3 rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.08] dark:bg-fog/[0.03]">
          <p className="text-[11px] font-semibold text-ink dark:text-fog">
            {valid.length} selected → {valid.length} WhatsApp message{valid.length === 1 ? "" : "s"} from your plan
          </p>
          <p className="mt-0.5 text-[10px] text-ink/50 dark:text-fog/50">
            {maxMessages === null
              ? "Your plan has unlimited messages."
              : `${usedMessages} used · ${remaining} remaining this month on ${entitlements.plan_name}`}
          </p>
          {quotaShort && (
            <p className="mt-1 text-[10px] font-semibold text-amber-700 dark:text-amber-400">
              Only {remaining} can be queued now; {valid.length - (remaining ?? 0)} will be skipped for quota. Upgrade the plan to send more.
            </p>
          )}
        </div>
      )}

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between gap-2">
          <span className="text-[11px] font-semibold text-ink/60 dark:text-fog/60">
            Template <span className="font-normal text-ink/35 dark:text-fog/35">({"name"} and {"link"} are replaced)</span>
          </span>
          <button
            onClick={() => void writeWithAi()}
            disabled={aiBusy}
            className="rounded-lg bg-deep-violet/10 px-2.5 py-1 text-[10px] font-bold text-deep-violet transition hover:bg-deep-violet/15 disabled:opacity-50"
          >
            {aiBusy ? "Writing…" : "Write with AI"}
          </button>
        </div>
        {channel === "email" && (
          <input
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            className="mb-2 w-full rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            placeholder="Subject"
          />
        )}
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={3}
          className="w-full rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[12px] text-ink dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
        />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          onClick={() => void send()}
          disabled={busy || valid.length === 0}
          className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-40"
        >
          {busy ? "Queueing…" : `Queue ${valid.length || ""} request${valid.length === 1 ? "" : "s"}`}
        </button>
        {message && <p className="text-[11px] text-ink/60 dark:text-fog/60">{message}</p>}
      </div>

      <p className="mt-3 text-[10px] text-ink/40 dark:text-fog/40">
        Batches are sent by the durable job worker, so closing the tab does not stop them. WhatsApp free-form messages require an open 24-hour customer window; outside it, Meta rejects the send and it shows as failed (an approved template is the production fix). Delivery failures appear in the Growth funnel, never as sent.
      </p>
    </section>
  );
}
