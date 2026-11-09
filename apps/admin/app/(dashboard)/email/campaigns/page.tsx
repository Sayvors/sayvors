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
  fetchCampaignTemplates,
  fetchCampaignVariables,
  fetchEmailCampaigns,
  previewEmailCampaign,
  startEmailCampaign,
  type CampaignAudience,
  type CampaignAudienceItem,
  type CampaignPreview,
  type CampaignRecipient,
  type CampaignTemplate,
  type CampaignVariable,
  type EmailCampaign,
} from "@/lib/admin-api";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-deep-violet";

const EDITOR_TOOLS: {
  label: string;
  title: string;
  command?: string;
  value?: string;
}[] = [
  { label: "B", title: "Bold", command: "bold" },
  { label: "I", title: "Italic", command: "italic" },
  { label: "H2", title: "Heading", command: "formatBlock", value: "<h2>" },
  { label: "H3", title: "Subheading", command: "formatBlock", value: "<h3>" },
  { label: "P", title: "Paragraph", command: "formatBlock", value: "<p>" },
  { label: "•", title: "Bullet list", command: "insertUnorderedList" },
  { label: "Link", title: "Insert link" },
];

const DEFAULT_BODY_HTML = `<h2 dir="rtl" style="text-align:right">مرحباً {name}،</h2>
<p dir="rtl" style="text-align:right">هذا الأسبوع جمعت مساحتك <strong>{reviews} تقييماً</strong> بمتوسط تقييم <strong>{avg_rating}</strong>.</p>
<p dir="rtl" style="text-align:right"><a href="{dashboard_url}">افتح لوحة التحكم</a> لرؤيتها والرد حيث يلزم.</p>
<p dir="rtl" style="text-align:right">اقرأ المزيد على <a href="https://sayvors.com/blog">مدونتنا</a>.</p>
<hr>
<h2 dir="ltr">Hi {name},</h2>
<p>This weekend your workspace collected <strong>{reviews} reviews</strong> with an average rating of <strong>{avg_rating}</strong>.</p>
<p><a href="{dashboard_url}">Open your dashboard</a> to see them and reply where needed.</p>
<p>Read more on our <a href="https://sayvors.com/blog">blog</a>.</p>`;

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
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [html, setHtml] = useState(DEFAULT_BODY_HTML);
  const [variables, setVariables] = useState<CampaignVariable[]>([]);
  const [templates, setTemplates] = useState<CampaignTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [preview, setPreview] = useState<CampaignPreview | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const editorRef = useRef<HTMLDivElement | null>(null);
  const previewSeq = useRef(0);
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
    fetchCampaignVariables()
      .then((data) => setVariables(data.items))
      .catch(() => {
        /* palette is helpful, not required to compose */
      });
    fetchCampaignTemplates()
      .then((data) => setTemplates(data.items))
      .catch(() => {
        /* templates are a shortcut; composing still works */
      });
  }, []);

  useEffect(() => {
    // Uncontrolled editor: seed the default body once, then let the browser
    // own the caret/DOM. State is mirrored on input for create/preview.
    if (editorRef.current && !editorRef.current.innerHTML.trim()) {
      editorRef.current.innerHTML = DEFAULT_BODY_HTML;
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
        name: name.trim() || undefined,
        subject: subject.trim(),
        html,
        text: editorRef.current?.innerText?.trim() || null,
        batch_size: batchSize,
        interval_seconds: intervalSeconds,
      });
      setNotice(`Draft created: ${campaign.name}. Review it, then press Start.`);
      setName("");
      setSubject("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create the campaign.");
    } finally {
      setBusy(null);
    }
  };

  const exec = (command: string, value?: string) => {
    editorRef.current?.focus();
    document.execCommand(command, false, value);
    if (editorRef.current) setHtml(editorRef.current.innerHTML);
  };

  const addLink = () => {
    const url = window.prompt("Link URL", "https://");
    if (url?.trim()) exec("createLink", url.trim());
  };

  const applyTemplate = (id: string) => {
    setTemplateId(id);
    const template = templates.find((item) => item.id === id);
    if (!template) return;
    setName(template.name);
    setSubject(template.subject);
    setHtml(template.body_html);
    if (editorRef.current) editorRef.current.innerHTML = template.body_html;
    setPreview(null);
  };

  const insertVariable = (key: string) => {
    const token = `{${key}}`;
    const editor = editorRef.current;
    if (!editor) {
      setHtml((previous) => previous + token);
      return;
    }
    editor.focus();
    const selection = window.getSelection();
    if (
      selection &&
      selection.rangeCount > 0 &&
      editor.contains(selection.anchorNode)
    ) {
      document.execCommand("insertText", false, token);
    } else {
      editor.innerHTML += token;
    }
    setHtml(editor.innerHTML);
  };

  const refreshPreview = useCallback(async () => {
    if (!subject.trim() || !html.trim()) return;
    const seq = ++previewSeq.current;
    setPreviewBusy(true);
    setError(null);
    try {
      const data = await previewEmailCampaign({
        subject: subject.trim(),
        html,
        text: editorRef.current?.innerText?.trim() || null,
      });
      if (seq === previewSeq.current) setPreview(data);
    } catch (e) {
      if (seq === previewSeq.current) {
        setError(e instanceof Error ? e.message : "Could not render the preview.");
      }
    } finally {
      if (seq === previewSeq.current) setPreviewBusy(false);
    }
  }, [subject, html]);

  useEffect(() => {
    if (!subject.trim() || !html.trim()) return;
    const timer = window.setTimeout(() => void refreshPreview(), 700);
    return () => window.clearTimeout(timer);
  }, [refreshPreview, subject, html]);

  const resetBody = () => {
    if (
      editorRef.current &&
      !window.confirm("Replace the current body with the default content?")
    ) {
      return;
    }
    setHtml(DEFAULT_BODY_HTML);
    if (editorRef.current) editorRef.current.innerHTML = DEFAULT_BODY_HTML;
    setPreview(null);
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
          Write with the toolbar. Variables are replaced per recipient at send time;
          the branded footer adds the unsubscribe link.
        </p>

        {templates.length > 0 && (
          <label className="mt-4 block">
            <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
              Start from a template
            </span>
            <select
              value={templateId}
              onChange={(e) => applyTemplate(e.target.value)}
              className="mt-1 h-9 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] text-ink"
            >
              <option value="">Blank / current draft</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name} — {template.description}
                </option>
              ))}
            </select>
          </label>
        )}

        <label className="mt-3 block">
          <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
            Campaign name
          </span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={120}
            placeholder="Weekly updates"
            className="mt-1 h-9 w-full rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[12px] text-ink"
          />
          <span className="mt-1 block text-[10px] text-ink/35">
            Admin label for this list. Falls back to the subject if left blank.
          </span>
        </label>

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
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

        <div className="mt-3 grid gap-4 lg:grid-cols-2">
          <div>
          <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
            Body
          </span>
          <div className="mt-1 flex flex-wrap items-center gap-1 rounded-t-[2px] border border-[var(--ui-line)] bg-[var(--ui-sunken)] p-1">
            {EDITOR_TOOLS.map((item) => (
              <button
                key={item.label}
                type="button"
                title={item.title}
                aria-label={item.title}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() =>
                  item.command ? exec(item.command, item.value) : addLink()
                }
                className={`h-7 min-w-7 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-1.5 text-[11px] text-ink/70 hover:bg-[var(--ui-sunken)] ${
                  item.label === "B" ? "font-bold" : ""
                } ${item.label === "I" ? "italic" : ""} ${FOCUS}`}
              >
                {item.label}
              </button>
            ))}
            <button
              type="button"
              title="Reset body to the default"
              onClick={resetBody}
              className={`ml-auto h-7 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[10.5px] font-semibold text-ink/60 hover:bg-[var(--ui-sunken)] ${FOCUS}`}
            >
              Reset
            </button>
          </div>
          <div
            ref={editorRef}
            contentEditable
            suppressContentEditableWarning
            role="textbox"
            aria-multiline="true"
            aria-label="Campaign body"
            onInput={(e) => setHtml(e.currentTarget.innerHTML)}
            className="min-h-[200px] rounded-b-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] p-3 text-[12.5px] leading-relaxed text-ink focus:outline-none [&_a]:text-deep-violet [&_a]:underline [&_h2]:mb-2 [&_h2]:text-[16px] [&_h2]:font-bold [&_h3]:mb-1.5 [&_h3]:text-[13.5px] [&_h3]:font-bold [&_li]:ml-4 [&_li]:list-disc [&_p]:mb-2"
          />
          <span className="mt-1 block text-[10px] text-ink/35">
            Use the toolbar for bold, italic, headings, lists and links. The stored
            email body is generated from this editor.
          </span>

        {variables.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/35">
              Variables
            </span>
            {variables.map((variable) => (
              <button
                key={variable.key}
                type="button"
                title={`${variable.label} (e.g. ${variable.example})`}
                onClick={() => insertVariable(variable.key)}
                className={`rounded-full border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 py-0.5 font-mono text-[10px] text-ink/65 hover:bg-[var(--ui-sunken)] ${FOCUS}`}
              >
                {`{${variable.key}}`}
              </button>
            ))}
          </div>
        )}
          </div>

          <div className="flex min-h-[280px] flex-col rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)]">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--ui-line)] px-3 py-2">
              <div className="min-w-0">
                <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40">
                  Live design preview
                </p>
                <p className="truncate text-[12px] font-bold text-ink">
                  {preview?.subject || subject || "Untitled subject"}
                </p>
                <p className="text-[10px] text-ink/40">
                  {preview
                    ? `Tenant: ${preview.tenant.email || "—"}`
                    : "The branded shell renders here as you type"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void refreshPreview()}
                disabled={previewBusy}
                className={`h-7 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-2 text-[10.5px] font-semibold text-ink disabled:opacity-50 ${FOCUS}`}
              >
                {previewBusy ? "Rendering…" : "Refresh"}
              </button>
            </div>
            {preview ? (
              <iframe
                title="Campaign preview"
                srcDoc={preview.html}
                sandbox=""
                className="h-[520px] w-full flex-1 bg-white"
              />
            ) : (
              <div className="flex flex-1 items-center justify-center p-6 text-center text-[11.5px] text-ink/40">
                The full branded email — logo, header, body and footer — appears
                here. Add a subject and body and it updates automatically.
              </div>
            )}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void create()}
            disabled={busy === "create"}
            className={`h-9 rounded-[2px] bg-deep-violet px-3 text-[12px] font-bold text-white disabled:opacity-50 ${FOCUS}`}
          >
            {busy === "create" ? "Creating…" : "Create draft"}
          </button>
          <button
            type="button"
            onClick={() => void refreshPreview()}
            disabled={previewBusy}
            className={`h-9 rounded-[2px] border border-[var(--ui-line)] bg-[var(--ui-surface)] px-3 text-[12px] font-semibold text-ink disabled:opacity-50 ${FOCUS}`}
          >
            {previewBusy ? "Rendering…" : "Refresh preview"}
          </button>
          <span className="text-[10.5px] text-ink/40">
            The preview uses a real eligible tenant. A draft does not send anything.
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
                          {campaign.name || campaign.subject}
                        </h3>
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${status.pill}`}>
                          {status.label}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[10.5px] text-ink/40">
                        Subject: {campaign.subject} · Created{" "}
                        {fmtDate(campaign.created_at)} by {campaign.created_by || "—"} ·{" "}
                        {campaign.batch_size}/batch every {campaign.interval_seconds}s
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
