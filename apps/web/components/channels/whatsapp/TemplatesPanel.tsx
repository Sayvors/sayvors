"use client";

/* Templates tab inside the WhatsApp hub.
 *
 * Templates are authored here and reviewed by Meta; sending happens from the
 * conversation, where the consent basis and the closed window are visible.
 * "Sync" still reconciles templates made in WhatsApp Manager.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n/I18nProvider";
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

function StatusChip({ status, label }: { status: string; label: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${STATUS_STYLE[status] ?? "bg-[var(--wa-panel-2)] text-[var(--wa-text-3)]"}`}>
      {label}
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

function when(value: string | null, locale: string, never: string): string {
  if (!value) return never;
  return new Date(value).toLocaleString(locale === "ar" ? "ar-SA" : "en-US");
}

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [key, val]) => out.replaceAll(`{${key}}`, String(val)),
    s,
  );
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
  const { t } = useI18n();
  const tp = t.templates;
  const e = tp.editor;
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
      setError(e.errName);
      return;
    }
    if (!body.trim()) {
      setError(e.errBody);
      return;
    }
    if (vars > 0 && examples.slice(0, vars).some((v) => !v.trim())) {
      setError(
        vars === 1
          ? e.errVarsOne
          : fill(e.errVars, { count: vars }),
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
        onSaved(e.savedEdit);
      } else {
        await createWhatsAppTemplate({
          name: cleanName,
          language: language.trim(),
          category,
          body,
          examples: examples.slice(0, vars),
        });
        onSaved(e.savedNew);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : e.errSave);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className={`${CARD} overflow-hidden`}>
      <div className="flex items-center justify-between border-b border-[var(--wa-border)] px-4 py-2.5">
        <div>
          <p className="text-[13px] font-semibold text-[var(--wa-text)]">
            {editing ? fill(e.editTitle, { name: template?.name ?? "" }) : e.newTitle}
          </p>
          <p className="text-[11px] text-[var(--wa-text-3)]">
            {editing ? e.editHint : e.newHint}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-full px-3 py-1 text-[11px] font-semibold text-[var(--wa-text-2)] hover:bg-[var(--wa-hover)] hover:text-[var(--wa-text)]"
        >
          {tp.cancel}
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
              {e.name}
            </label>
            <input
              id="tpl-name"
              value={name}
              onChange={(ev) => setName(ev.target.value)}
              disabled={editing}
              placeholder="order_ready"
              className={`${INPUT} disabled:opacity-60`}
            />
            <p className="mt-1 text-[10.5px] text-[var(--wa-text-3)]">
              {e.nameHint}
            </p>
          </div>
          <div>
            <label className={LABEL} htmlFor="tpl-language">
              {e.language}
            </label>
            <input
              id="tpl-language"
              value={language}
              onChange={(ev) => setLanguage(ev.target.value)}
              disabled={editing}
              placeholder="en_US"
              className={`${INPUT} disabled:opacity-60`}
            />
            <p className="mt-1 text-[10.5px] text-[var(--wa-text-3)]">
              {e.languageHint}
            </p>
          </div>
          <div>
            <label className={LABEL} htmlFor="tpl-category">
              {e.category}
            </label>
            <select
              id="tpl-category"
              value={category}
              onChange={(ev) => setCategory(ev.target.value)}
              className={INPUT}
            >
              {CATEGORIES.map((value) => (
                <option key={value} value={value}>
                  {tp.categories[value as keyof typeof tp.categories]}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className={LABEL} htmlFor="tpl-body">
            {e.body}
          </label>
          <textarea
            id="tpl-body"
            value={body}
            onChange={(ev) => changeBody(ev.target.value)}
            rows={4}
            maxLength={1024}
            placeholder="مرحباً {{1}}، طلبك {{2}} جاهز للاستلام."
            className={`${INPUT} resize-y leading-5`}
          />
          <div className="mt-1 flex items-center justify-between text-[10.5px] text-[var(--wa-text-3)]">
            <span>
              {e.bodyHint}
            </span>
            <span>{body.length}/1024</span>
          </div>
        </div>

        {vars > 0 && (
          <fieldset>
            <legend className={LABEL}>{e.samples}</legend>
            <div className="grid gap-2 sm:grid-cols-2">
              {Array.from({ length: vars }, (_, index) => (
                <div key={index} className="flex items-center gap-2">
                  <span className="w-10 shrink-0 text-[11px] font-semibold text-[var(--wa-text-3)]">
                    {`{{${index + 1}}}`}
                  </span>
                  <input
                    value={examples[index] ?? ""}
                    onChange={(ev) =>
                      setExamples((prev) =>
                        prev.map((value, i) =>
                          i === index ? ev.target.value : value,
                        ),
                      )
                    }
                    placeholder={
                      index === 0 ? "Sara" : index === 1 ? "A-1042" : "sample"
                    }
                    aria-label={fill(e.sampleAria, { n: index + 1 })}
                    className={INPUT}
                  />
                </div>
              ))}
            </div>
            <p className="mt-1 text-[10.5px] text-[var(--wa-text-3)]">
              {e.samplesHint}
            </p>
          </fieldset>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-[var(--wa-border)] pt-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full px-3 py-1.5 text-[12px] font-semibold text-[var(--wa-text-2)] hover:bg-[var(--wa-hover)]"
          >
            {tp.cancel}
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy}
            className="rounded-full bg-[var(--wa-accent)] px-4 py-1.5 text-[12px] font-bold text-white disabled:opacity-50"
          >
            {busy
              ? e.saving
              : editing
                ? e.saveChanges
                : e.submitMeta}
          </button>
        </div>
      </div>
    </section>
  );
}

export default function TemplatesPanel() {
  const { t, locale } = useI18n();
  const tp = t.templates;
  const fmt = (n: number) =>
    new Intl.NumberFormat(locale === "ar" ? "ar-SA" : "en-US").format(n);
  const whenAt = (value: string | null) => when(value, locale, tp.never);
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
      setError(e instanceof Error ? e.message : tp.errors.load);
    } finally {
      setLoading(false);
    }
  }, [tp]);

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
        result.created + result.updated === 1
          ? tp.noticeSyncedOne
          : fill(tp.noticeSynced, {
              count: fmt(result.created + result.updated),
            }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : tp.errors.sync);
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
      setNotice(fill(tp.noticeDeleted, { name: template.name }));
    } catch (e) {
      setError(e instanceof Error ? e.message : tp.errors.remove);
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
        e instanceof Error ? e.message : tp.errors.analytics,
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
            {tp.noWabaTitle}
          </p>
          <p className="mt-0.5">
            {tp.noWabaBody}{" "}
            <a href="?tab=numbers" className="font-semibold underline">
              {tp.openNumbers}
            </a>
          </p>
        </div>
      )}
      {wabaKnown && waba.connected && waba.name && (
        <p className="px-1 text-[11px] text-[var(--wa-text-3)]">
          {tp.wabaLabel}{" "}
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
          { label: tp.stats.approved, value: counts.approved },
          { label: tp.stats.pending, value: counts.pending },
          { label: tp.stats.utility, value: counts.utility },
        ].map((card) => (
          <div key={card.label} className={`${CARD} px-4 py-3`}>
            <p className="text-[10px] font-bold uppercase tracking-widest text-[var(--wa-text-3)]">
              {card.label}
            </p>
            <p className="mt-0.5 text-[20px] font-semibold text-[var(--wa-text)]">
              {fmt(card.value)}
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
              {tp.filters[key]}
            </button>
          ))}
          <span className="ml-auto text-[11px] text-[var(--wa-text-3)]">
            {fill(tp.shown, { count: fmt(visible.length) })}
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
            {tp.newTemplate}
          </button>
          <button
            type="button"
            onClick={() => void sync()}
            disabled={syncing || !waba.connected}
            className="rounded-full bg-[var(--wa-accent)] px-3 py-1 text-[11px] font-bold text-white disabled:opacity-50"
          >
            {syncing ? tp.syncing : tp.sync}
          </button>
        </div>

        {loading ? (
          <p className="px-4 py-8 text-center text-[12px] text-[var(--wa-text-3)]">
            {tp.loading}
          </p>
        ) : visible.length === 0 ? (
          <div className="px-4 py-8 text-center">
            <p className="text-[13px] font-medium text-[var(--wa-text-2)]">
              {templates.length === 0
                ? tp.emptyNone
                : tp.emptyFilter}
            </p>
            <p className={`mx-auto mt-1 max-w-md ${MUTED}`}>
              {templates.length === 0 && !wabaKnown
                ? tp.emptyStateUnknown
                : templates.length === 0 && waba.connected
                  ? tp.emptyStateConnected
                  : templates.length === 0
                    ? tp.emptyStateNoWaba
                    : tp.emptyStateFiltered}
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
                      {tp.categories[t.category as keyof typeof tp.categories] ?? t.category}
                    </span>
                    <span className="text-[11px] font-medium text-[var(--wa-text-3)]">
                      {t.language}
                    </span>
                    <StatusChip status={t.status} label={tp.status[t.status as keyof typeof tp.status] ?? t.status} />
                  </div>
                  <p className="mt-1 whitespace-pre-line text-[12px] leading-5 text-[var(--wa-text-2)]">
                    {t.body || tp.noBody}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px] text-[var(--wa-text-3)]">
                    <span>
                      {t.variables > 0
                        ? t.variables === 1
                          ? tp.varsOne
                          : fill(tp.varsN, { count: fmt(t.variables) })
                        : tp.noVars}
                    </span>
                    <span>
                      {t.send_count === 1
                        ? tp.attemptsOne
                        : fill(tp.attempts, { count: fmt(t.send_count) })}
                    </span>
                    {t.failed_count > 0 && (
                      <span className="font-semibold text-[#C4304B]">
                        {fill(tp.failedN, { count: fmt(t.failed_count) })}
                      </span>
                    )}
                    <span>{fill(tp.lastSend, { when: whenAt(t.last_sent_at) })}</span>
                    {t.last_synced_at && (
                      <span>
                        {fill(tp.syncedAt, { when: whenAt(t.last_synced_at) })}
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
                            ? tp.tipSyncEdit
                            : tp.tipAuthEdit
                          : undefined
                      }
                      className="rounded-full bg-[var(--wa-panel-2)] px-2.5 py-1 text-[10.5px] font-semibold text-[var(--wa-text-2)] hover:text-[var(--wa-text)] disabled:opacity-50"
                    >
                      {tp.edit}
                    </button>
                    <button
                      type="button"
                      onClick={() => void toggleAnalytics(t)}
                      aria-expanded={isOpen}
                      className="rounded-full bg-[var(--wa-panel-2)] px-2.5 py-1 text-[10.5px] font-semibold text-[var(--wa-text-2)] hover:text-[var(--wa-text)]"
                    >
                      {isOpen ? tp.hideAnalytics : tp.analytics}
                    </button>
                    {confirmDelete === t.id ? (
                      <span className="flex items-center gap-1.5">
                        <span className="text-[10.5px] text-[var(--wa-text-2)]">
                          {tp.deleteConfirm}
                        </span>
                        <button
                          type="button"
                          onClick={() => void remove(t)}
                          disabled={deleting === t.id}
                          className="rounded-full bg-[#C4304B] px-2.5 py-1 text-[10.5px] font-bold text-white disabled:opacity-50"
                        >
                          {deleting === t.id ? tp.deleting : tp.delete}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(null)}
                          className="rounded-full px-2 py-1 text-[10.5px] font-semibold text-[var(--wa-text-2)] hover:bg-[var(--wa-hover)]"
                        >
                          {tp.cancel}
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmDelete(t.id)}
                        disabled={t.meta_template_id === null}
                        title={
                          t.meta_template_id === null
                            ? tp.tipSyncDelete
                            : undefined
                        }
                        className="rounded-full px-2.5 py-1 text-[10.5px] font-semibold text-[var(--wa-text-3)] hover:bg-[#FF4F6E]/10 hover:text-[#C4304B] disabled:opacity-50"
                      >
                        {tp.delete}
                      </button>
                    )}
                  </div>

                  {isOpen && (
                    <div className="mt-2 rounded-lg bg-[var(--wa-panel-2)] px-3 py-2.5">
                      {analyticsBusy === t.id ? (
                        <p className="text-[11px] text-[var(--wa-text-3)]">
                          {tp.loadingAnalytics}
                        </p>
                      ) : stats ? (
                        <>
                          <div className="flex flex-wrap gap-4">
                            <span className="text-[11px] text-[var(--wa-text-2)]">
                              <strong className="text-[var(--wa-text)]">
                                {fmt(stats.sent)}
                              </strong>{" "}
                              {tp.sent}
                            </span>
                            <span className="text-[11px] text-[var(--wa-text-2)]">
                              <strong className="text-[var(--wa-text)]">
                                {fmt(stats.failed)}
                              </strong>{" "}
                              {tp.failed}
                            </span>
                            <span className="text-[11px] text-[var(--wa-text-2)]">
                              <strong className="text-[var(--wa-text)]">
                                {fmt(stats.blocked)}
                              </strong>{" "}
                              {tp.blocked}
                            </span>
                            <span className="text-[11px] text-[var(--wa-text-3)]">
                              {fill(tp.lastDays, { days: fmt(stats.days) })}
                            </span>
                          </div>
                          <p className="mt-1 text-[10.5px] text-[var(--wa-text-3)]">
                            {fill(tp.lastAttempt, { when: whenAt(stats.last_sent_at) })}
                          </p>
                        </>
                      ) : (
                        <p className="text-[11px] text-[var(--wa-text-3)]">
                          {tp.noAnalytics}
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
        {tp.footer}
      </p>
    </div>
  );
}
