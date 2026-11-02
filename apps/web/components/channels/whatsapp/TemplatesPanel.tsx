"use client";

/* Templates tab inside the WhatsApp hub.
 *
 * Templates are authored here and reviewed by Meta; sending happens from the
 * conversation, where the consent basis and the closed window are visible.
 * "Sync" still reconciles templates made in WhatsApp Manager.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createWhatsAppTemplate,
  deleteWhatsAppTemplate,
  getWhatsAppTemplateAnalytics,
  listWhatsAppTemplates,
  syncWhatsAppTemplates,
  updateWhatsAppTemplate,
  type TemplateAnalytics,
  type WabaConnection,
  type WhatsAppTemplate,
} from "@/lib/api-whatsapp-templates";

const CARD =
  "rounded-lg bg-[var(--wa-panel)] shadow-[0_1px_2px_rgba(0,0,0,0.12)]";
const MUTED = "text-[12px] text-[var(--wa-text-2)]";
const INPUT =
  "w-full rounded-lg border border-[var(--wa-input-border)] bg-[var(--wa-input-bg)] px-3 py-2 text-[13px] text-[var(--wa-text)] outline-none placeholder:text-[var(--wa-text-3)] focus:border-[var(--wa-accent)] focus:ring-2 focus:ring-[var(--wa-accent)]/25";
const LABEL =
  "mb-1 block text-[10px] font-bold uppercase tracking-widest text-[var(--wa-text-3)]";

const STATUS_STYLE: Record<string, string> = {
  approved: "bg-[var(--wa-accent)]/12 text-[var(--wa-accent-deep)]",
  pending: "bg-amber-100 text-amber-700",
  rejected: "bg-[#FF4F6E]/10 text-[#C4304B]",
};

const CATEGORIES = ["utility", "marketing"];
const EDITABLE_CATEGORIES = new Set(CATEGORIES);

function StatusChip({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${STATUS_STYLE[status] ?? "bg-[var(--wa-panel-2)] text-[var(--wa-text-3)]"}`}>
      {status}
    </span>
  );
}

function variableCount(body: string): number {
  let highest = 0;
  for (const match of body.matchAll(/\{\{\s*(\d+)\s*\}\}/g)) {
    highest = Math.max(highest, Number(match[1]));
  }
  return highest;
}

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "never";
}

function TemplateEditor({
  template,
  onClose,
  onSaved,
}: {
  template?: WhatsAppTemplate;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const editing = Boolean(template);
  const [name, setName] = useState(template?.name ?? "");
  const [language, setLanguage] = useState(template?.language ?? "en_US");
  const [category, setCategory] = useState(template?.category ?? "utility");
  const [body, setBody] = useState(template?.body ?? "");
  const [examples, setExamples] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const vars = variableCount(body);

  const changeBody = (value: string) => {
    setBody(value);
    const count = variableCount(value);
    setExamples((prev) =>
      Array.from({ length: count }, (_, index) => prev[index] ?? ""),
    );
  };

  const submit = async () => {
    setError(null);
    const cleanName = name.trim().toLowerCase();
    if (!editing && !/^[a-z0-9_]{1,512}$/.test(cleanName)) {
      setError(
        "Name must be 1–512 lowercase letters, numbers or underscores.",
      );
      return;
    }
    if (!body.trim()) {
      setError("Write the message body.");
      return;
    }
    if (vars > 0 && examples.slice(0, vars).some((v) => !v.trim())) {
      setError(
        `This template has ${vars} variable${vars === 1 ? "" : "s"}. Add a sample value for each one.`,
      );
      return;
    }
    setBusy(true);
    try {
      if (template) {
        await updateWhatsAppTemplate(template.id, {
          category,
          body,
          examples: examples.slice(0, vars),
        });
        onSaved("Saved. Meta reviews the change before it can be sent again.");
      } else {
        await createWhatsAppTemplate({
          name: cleanName,
          language: language.trim(),
          category,
          body,
          examples: examples.slice(0, vars),
        });
        onSaved(
          "Template submitted to Meta. It can be sent once it is approved.",
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save the template.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`${CARD} overflow-hidden`}>
      <div className="flex items-center justify-between border-b border-[var(--wa-border)] px-4 py-2.5">
        <div>
          <p className="text-[13px] font-semibold text-[var(--wa-text)]">
            {editing ? `Edit ${template?.name}` : "New template"}
          </p>
          <p className="text-[11px] text-[var(--wa-text-3)]">
            {editing
              ? "Meta does not allow renaming a template or changing its language. The body can be edited."
              : "Meta reviews every new template. Utility templates such as order updates are the usual first step."}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full px-3 py-1 text-[11px] font-semibold text-[var(--wa-text-2)] hover:bg-[var(--wa-hover)] hover:text-[var(--wa-text)]"
        >
          Cancel
        </button>
      </div>

      <div className="space-y-3 px-4 py-3">
        {error && (
          <p
            role="alert"
            className="rounded-lg bg-[var(--wa-warn-bg)] px-3 py-2 text-[12px] text-[var(--wa-warn-text)]"
          >
            {error}
          </p>
        )}

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label className={LABEL} htmlFor="tpl-name">
              Name
            </label>
            <input
              id="tpl-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={editing}
              placeholder="order_ready"
              className={`${INPUT} disabled:opacity-60`}
            />
            <p className="mt-1 text-[10.5px] text-[var(--wa-text-3)]">
              Lowercase letters, numbers and underscores.
            </p>
          </div>
          <div>
            <label className={LABEL} htmlFor="tpl-language">
              Language
            </label>
            <input
              id="tpl-language"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={editing}
              placeholder="en_US"
              className={`${INPUT} disabled:opacity-60`}
            />
            <p className="mt-1 text-[10.5px] text-[var(--wa-text-3)]">
              Meta code, e.g. en_US, ar or ur.
            </p>
          </div>
          <div>
            <label className={LABEL} htmlFor="tpl-category">
              Category
            </label>
            <select
              id="tpl-category"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className={INPUT}
            >
              {CATEGORIES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className={LABEL} htmlFor="tpl-body">
            Body
          </label>
          <textarea
            id="tpl-body"
            value={body}
            onChange={(e) => changeBody(e.target.value)}
            rows={4}
            maxLength={1024}
            placeholder="Hi {{1}}, your order {{2}} is ready for pickup."
            className={`${INPUT} resize-y leading-5`}
          />
          <div className="mt-1 flex items-center justify-between text-[10.5px] text-[var(--wa-text-3)]">
            <span>
              Use {"{{1}}"}, {"{{2}}"}… for customer-specific details.
            </span>
            <span>{body.length}/1024</span>
          </div>
        </div>

        {vars > 0 && (
          <fieldset>
            <legend className={LABEL}>Sample values for review</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {Array.from({ length: vars }, (_, index) => (
                <div key={index} className="flex items-center gap-2">
                  <span className="w-10 shrink-0 text-[11px] font-semibold text-[var(--wa-text-3)]">
                    {`{{${index + 1}}}`}
                  </span>
                  <input
                    value={examples[index] ?? ""}
                    onChange={(e) =>
                      setExamples((prev) =>
                        prev.map((value, i) =>
                          i === index ? e.target.value : value,
                        ),
                      )
                    }
                    placeholder={
                      index === 0 ? "Sara" : index === 1 ? "A-1042" : "sample"
                    }
                    aria-label={`Sample value for variable ${index + 1}`}
                    className={INPUT}
                  />
                </div>
              ))}
            </div>
            <p className="mt-1 text-[10.5px] text-[var(--wa-text-3)]">
              Meta needs a realistic example for every variable. Customers never
              see these values.
            </p>
          </fieldset>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-[var(--wa-border)] pt-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-3 py-1.5 text-[12px] font-semibold text-[var(--wa-text-2)] hover:bg-[var(--wa-hover)]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy}
            className="rounded-full bg-[var(--wa-accent)] px-4 py-1.5 text-[12px] font-bold text-white disabled:opacity-50"
          >
            {busy
              ? "Saving…"
              : editing
                ? "Save changes"
                : "Submit to Meta"}
          </button>
        </div>
      </div>
    </section>
  );
}

export default function TemplatesPanel() {
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [waba, setWaba] = useState<WabaConnection>({
    connected: false,
    name: null,
  });
  const [wabaKnown, setWabaKnown] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "approved" | "utility">("all");
  const [editing, setEditing] = useState<WhatsAppTemplate | "new" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [analytics, setAnalytics] = useState<Record<string, TemplateAnalytics>>(
    {},
  );
  const [analyticsBusy, setAnalyticsBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await listWhatsAppTemplates();
      setTemplates(result.templates);
      setWaba(result.waba);
      setWabaKnown(true);
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
    setError(null);
    try {
      const result = await syncWhatsAppTemplates();
      setTemplates(result.templates);
      setWaba(result.waba);
      setWabaKnown(true);
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

  const saved = async (message: string) => {
    setEditing(null);
    setError(null);
    setNotice(message);
    await load();
  };

  const remove = async (template: WhatsAppTemplate) => {
    setDeleting(template.id);
    setError(null);
    setNotice(null);
    try {
      await deleteWhatsAppTemplate(template.id);
      setTemplates((prev) => prev.filter((t) => t.id !== template.id));
      setAnalytics((prev) => {
        const next = { ...prev };
        delete next[template.id];
        return next;
      });
      if (expanded === template.id) setExpanded(null);
      setConfirmDelete(null);
      setNotice(`Deleted ${template.name} at Meta and here.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete the template.");
    } finally {
      setDeleting(null);
    }
  };

  const toggleAnalytics = async (template: WhatsAppTemplate) => {
    if (expanded === template.id) {
      setExpanded(null);
      return;
    }
    setExpanded(template.id);
    if (analytics[template.id]) return;
    setAnalyticsBusy(template.id);
    try {
      const result = await getWhatsAppTemplateAnalytics(template.id);
      setAnalytics((prev) => ({ ...prev, [template.id]: result }));
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not load template analytics.",
      );
    } finally {
      setAnalyticsBusy(null);
    }
  };

  const visible = useMemo(() => {
    if (filter === "approved") {
      return templates.filter((t) => t.status === "approved");
    }
    if (filter === "utility") {
      return templates.filter((t) => t.category === "utility");
    }
    return templates;
  }, [templates, filter]);

  const counts = useMemo(
    () => ({
      approved: templates.filter((t) => t.status === "approved").length,
      pending: templates.filter((t) => t.status === "pending").length,
      utility: templates.filter(
        (t) => t.category === "utility" && t.status === "approved",
      ).length,
    }),
    [templates],
  );

  return (
    <div className="space-y-3">
      {wabaKnown && !waba.connected && (
        <div className="rounded-lg bg-[var(--wa-warn-bg)] px-3 py-2 text-[12px] text-[var(--wa-warn-text)]">
          <p className="font-semibold">
            No WhatsApp Business Account is connected.
          </p>
          <p className="mt-0.5">
            Connect a WhatsApp number first, then come back to create
            templates.{" "}
            <a href="?tab=numbers" className="font-semibold underline">
              Open Numbers
            </a>
          </p>
        </div>
      )}
      {wabaKnown && waba.connected && waba.name && (
        <p className="px-1 text-[11px] text-[var(--wa-text-3)]">
          WhatsApp Business Account:{" "}
          <span className="font-semibold text-[var(--wa-text-2)]">
            {waba.name}
          </span>
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="rounded-lg bg-[var(--wa-warn-bg)] px-3 py-2 text-[12px] text-[var(--wa-warn-text)]"
        >
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

      {editing && (
        <TemplateEditor
          key={editing === "new" ? "new" : editing.id}
          template={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={(message) => void saved(message)}
        />
      )}

      <section className={CARD}>
        <div className="flex flex-wrap items-center gap-2 border-b border-[var(--wa-border)] px-4 py-2.5">
          {(["all", "approved", "utility"] as const).map((key) => (
            <button
              key={key}
              type="button"
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
            type="button"
            onClick={() => {
              setEditing("new");
              setNotice(null);
              setError(null);
            }}
            disabled={!waba.connected || editing !== null}
            className="rounded-full border border-[var(--wa-accent)] px-3 py-1 text-[11px] font-bold text-[var(--wa-accent-deep)] disabled:opacity-50"
          >
            New template
          </button>
          <button
            type="button"
            onClick={() => void sync()}
            disabled={syncing || !waba.connected}
            className="rounded-full bg-[var(--wa-accent)] px-3 py-1 text-[11px] font-bold text-white disabled:opacity-50"
          >
            {syncing ? "Syncing…" : "Sync from Meta"}
          </button>
        </div>

        {loading ? (
          <p className="px-4 py-8 text-center text-[12px] text-[var(--wa-text-3)]">
            Loading…
          </p>
        ) : visible.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <p className="text-[13px] font-medium text-[var(--wa-text-2)]">
              {templates.length === 0
                ? "No templates yet."
                : "Nothing matches this filter."}
            </p>
            <p className={`mx-auto mt-1 max-w-md ${MUTED}`}>
              {templates.length === 0 && !wabaKnown
                ? "Could not load the connection state. Reload the panel to try again."
                : templates.length === 0 && waba.connected
                  ? "Create a utility template here — for example an order update. Meta reviews it, then it can be sent outside the 24-hour window."
                  : templates.length === 0
                    ? "Connect a WhatsApp number, then create your first template here."
                    : "Try the All filter."}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-[var(--wa-border)]">
            {visible.map((t) => {
              const stats = analytics[t.id];
              const isOpen = expanded === t.id;
              const canEdit =
                t.meta_template_id !== null &&
                EDITABLE_CATEGORIES.has(t.category);
              return (
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
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-[var(--wa-text-3)]">
                    <span>
                      {t.variables > 0
                        ? `${t.variables} variable${t.variables === 1 ? "" : "s"}`
                        : "No variables"}
                    </span>
                    <span>
                      {t.send_count} attempt{t.send_count === 1 ? "" : "s"}
                    </span>
                    {t.failed_count > 0 && (
                      <span className="font-semibold text-[#C4304B]">
                        {t.failed_count} failed
                      </span>
                    )}
                    <span>last send {when(t.last_sent_at)}</span>
                    {t.last_synced_at && (
                      <span>
                        synced {new Date(t.last_synced_at).toLocaleString()}
                      </span>
                    )}
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setEditing(t);
                        setNotice(null);
                        setError(null);
                      }}
                      disabled={!canEdit}
                      title={
                        !canEdit
                          ? t.meta_template_id === null
                            ? "Sync from Meta before editing this template."
                            : "Authentication templates must be edited in WhatsApp Manager."
                          : undefined
                      }
                      className="rounded-full bg-[var(--wa-panel-2)] px-2.5 py-1 text-[10.5px] font-semibold text-[var(--wa-text-2)] hover:text-[var(--wa-text)] disabled:opacity-50"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => void toggleAnalytics(t)}
                      aria-expanded={isOpen}
                      className="rounded-full bg-[var(--wa-panel-2)] px-2.5 py-1 text-[10.5px] font-semibold text-[var(--wa-text-2)] hover:text-[var(--wa-text)]"
                    >
                      {isOpen ? "Hide analytics" : "Analytics"}
                    </button>
                    {confirmDelete === t.id ? (
                      <span className="flex items-center gap-1.5">
                        <span className="text-[10.5px] text-[var(--wa-text-2)]">
                          Delete at Meta and here? An approved name cannot be
                          reused for 30 days.
                        </span>
                        <button
                          type="button"
                          onClick={() => void remove(t)}
                          disabled={deleting === t.id}
                          className="rounded-full bg-[#C4304B] px-2.5 py-1 text-[10.5px] font-bold text-white disabled:opacity-50"
                        >
                          {deleting === t.id ? "Deleting…" : "Delete"}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(null)}
                          className="rounded-full px-2 py-1 text-[10.5px] font-semibold text-[var(--wa-text-2)] hover:bg-[var(--wa-hover)]"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmDelete(t.id)}
                        disabled={t.meta_template_id === null}
                        title={
                          t.meta_template_id === null
                            ? "Sync from Meta before deleting this template."
                            : undefined
                        }
                        className="rounded-full px-2.5 py-1 text-[10.5px] font-semibold text-[var(--wa-text-3)] hover:bg-[#FF4F6E]/10 hover:text-[#C4304B] disabled:opacity-50"
                      >
                        Delete
                      </button>
                    )}
                  </div>

                  {isOpen && (
                    <div className="mt-2 rounded-lg bg-[var(--wa-panel-2)] px-3 py-2.5">
                      {analyticsBusy === t.id ? (
                        <p className="text-[11px] text-[var(--wa-text-3)]">
                          Loading analytics…
                        </p>
                      ) : stats ? (
                        <>
                          <div className="flex flex-wrap gap-4">
                            <span className="text-[11px] text-[var(--wa-text-2)]">
                              <strong className="text-[var(--wa-text)]">
                                {stats.sent}
                              </strong>{" "}
                              sent
                            </span>
                            <span className="text-[11px] text-[var(--wa-text-2)]">
                              <strong className="text-[var(--wa-text)]">
                                {stats.failed}
                              </strong>{" "}
                              failed
                            </span>
                            <span className="text-[11px] text-[var(--wa-text-2)]">
                              <strong className="text-[var(--wa-text)]">
                                {stats.blocked}
                              </strong>{" "}
                              blocked
                            </span>
                            <span className="text-[11px] text-[var(--wa-text-3)]">
                              last {stats.days} days
                            </span>
                          </div>
                          <p className="mt-1 text-[10.5px] text-[var(--wa-text-3)]">
                            Last attempt {when(stats.last_sent_at)}. Blocked
                            means consent or approval was missing, so Meta was
                            never called.
                          </p>
                        </>
                      ) : (
                        <p className="text-[11px] text-[var(--wa-text-3)]">
                          No analytics available.
                        </p>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
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
