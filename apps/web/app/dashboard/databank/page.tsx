"use client";

import Link from "next/link";
import { useEffect, useState, Fragment, useMemo } from "react";
import {
  listDatabanks,
  deleteDatabank,
  listDocuments,
  retryDocuments,
  previewDocument,
  type DatabankDoc,
  type DocumentPreview,
} from "@/lib/api-rag";
import {
  getBusinessProfile,
  saveBusinessProfile,
  regenerateBusinessProfile,
  type BusinessProfileData,
} from "@/lib/api-business-profile";
import BusinessDetailsSection from "@/components/databank/BusinessDetailsSection";
import { useI18n } from "@/lib/i18n/I18nProvider";
import FeatureLock from "@/components/billing/FeatureLock";

type Databank = {
  id: string;
  name: string;
  description?: string;
  accent_color?: string;
  doc_count?: number;
  total_size?: number;
};

function formatBytes(bytes = 0): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const size = Math.floor(Math.log(bytes) / Math.log(1024));
  const value = bytes / 1024 ** size;
  return `${value.toFixed(1)} ${units[size]}`;
}

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

type BadgeLabels = {
  ready: string;
  processing: string;
  queued: string;
  failed: string;
  unknown: string;
  waiting: string;
};

function StatusBadge({ status, labels }: { status?: string; labels: BadgeLabels }) {
  const base = "inline-flex items-center gap-1.5 rounded-[2px] px-2.5 py-1 text-[10px] font-bold tracking-wide";
  if (status === "ready" || status === "completed" || status === "processed") {
    return (
      <span className={`${base} bg-emerald/10 text-emerald ring-1 ring-emerald/30`}>
        <span className="h-1.5 w-1.5 rounded-full bg-emerald" />
        {labels.ready}
      </span>
    );
  }
  if (status === "processing") {
    return (
      <span className={`${base} bg-amber/10 text-amber ring-1 ring-amber/30`}>
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber" />
        {labels.processing}
      </span>
    );
  }
  if (status === "pending" || status === "queued") {
    return (
      <span
        title={labels.waiting}
        className={`${base} bg-sky/10 text-sky ring-1 ring-sky/30`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-sky" />
        {labels.queued}
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className={`${base} bg-coral/10 text-coral ring-1 ring-coral/30`}>
        <span className="h-1.5 w-1.5 rounded-full bg-coral" />
        {labels.failed}
      </span>
    );
  }
  return (
    <span className={`${base} bg-foreground/5 text-foreground/40`}>
      {status || labels.unknown}
    </span>
  );
}

function FileIcon({ type }: { type?: string }) {
  const t = (type || "").toLowerCase();
  if (t.includes("pdf")) {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-[2px] bg-coral/10 text-coral ring-1 ring-coral/30">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M10 13H8v4h2a2 2 0 000-4z M14 13h-1v4h1a2 2 0 002-2 2 2 0 00-2-2z" />
        </svg>
      </span>
    );
  }
  if (t.includes("csv") || t.includes("xls")) {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-[2px] bg-emerald/10 text-emerald ring-1 ring-emerald/30">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 14h8M8 17h8" />
        </svg>
      </span>
    );
  }
  if (t.includes("doc")) {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-[2px] bg-sky/10 text-sky ring-1 ring-sky/30">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
          <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 13h6M8 17h6" />
        </svg>
      </span>
    );
  }
  return (
    <span className="flex h-8 w-8 items-center justify-center rounded-[2px] bg-accent-soft text-foreground/40">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-4 w-4">
        <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
        <path d="M14 2v6h6" />
      </svg>
    </span>
  );
}

const PROFILE_FIELD_META = [
  { key: "domain", placeholder: "e.g. Food & Restaurant", textarea: false },
  { key: "products_services", placeholder: "e.g. shawarma, mixed grill, catering", textarea: true },
  { key: "not_offered_and_policies", placeholder: "e.g. no alcohol, halal only, pickup until 11pm", textarea: true },
  { key: "audience_languages", placeholder: "e.g. local families and offices; Arabic & English", textarea: false },
] as const;

function profileFieldLabel(
  key: string,
  fields: { domain: string; offers: string; notOffered: string; audience: string },
): string {
  if (key === "domain") return fields.domain;
  if (key === "products_services") return fields.offers;
  if (key === "not_offered_and_policies") return fields.notOffered;
  return fields.audience;
}

function BusinessProfileCard() {
  const { t } = useI18n();
  const d = t.dashboard.databank.profile;
  const [profile, setProfile] = useState<BusinessProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const data = await getBusinessProfile();
        if (!cancelled) setProfile(data);
      } catch {
        /* the card is optional chrome — stay empty on failure */
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  function startEdit() {
    const next: Record<string, string> = {};
    for (const f of PROFILE_FIELD_META) next[f.key] = (profile?.[f.key] as string) ?? "";
    next.summary = profile?.summary ?? "";
    setForm(next);
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await saveBusinessProfile(form);
      setProfile(updated);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : d.saveFailed);
    } finally {
      setSaving(false);
    }
  }

  async function handleRegenerate() {
    setRegenerating(true);
    setError(null);
    try {
      const updated = await regenerateBusinessProfile();
      setProfile(updated);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : d.generateFailed);
    } finally {
      setRegenerating(false);
    }
  }

  const isEdited = profile?.source === "edited";
  const busy = saving || regenerating;

  return (
    <div className="rounded-[2px] border border-card-border bg-card shadow-sm">
      <div className="flex flex-col gap-3 border-b border-card-border px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-[2px] bg-gradient-to-br from-deep-violet to-violet-light text-white shadow-sm">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-4.5 w-4.5">
              <path d="M4 19.5A2.5 2.5 0 016.5 17H20" />
              <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-[15px] font-bold leading-tight text-foreground">{d.title}</h2>
              {profile && (
                <span
                  title={isEdited ? d.editedTitle : d.autoTitle}
                  className={`inline-flex items-center gap-1 rounded-[2px] px-2 py-0.5 text-[10px] font-bold ${
                    isEdited
                      ? "bg-sky/10 text-sky ring-1 ring-sky/30"
                      : "bg-accent-soft text-deep-violet ring-1 ring-violet-light/30 dark:text-violet-light"
                  }`}
                >
                  {isEdited ? d.editedByYou : d.autoGen}
                </span>
              )}
            </div>
            <p className="text-[11px] font-medium text-foreground/40">
              {d.subtitle}
            </p>
          </div>
        </div>
        {!editing && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleRegenerate()}
              disabled={busy}
              title={d.regenTitle}
              className="inline-flex items-center gap-1.5 rounded-[2px] border border-card-border bg-card px-3 py-2 text-[11px] font-bold text-foreground/60 transition hover:bg-foreground/[0.04] disabled:opacity-50"
            >
              {regenerating ? (
                <>
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-deep-violet/30 border-t-deep-violet" />
                  {d.reading}
                </>
              ) : (
                <>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                    <path d="M21 12a9 9 0 11-9-9" strokeLinecap="round" />
                    <path d="M9 9l3-3 3 3M9 15l3 3 3-3" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  {profile ? d.regenerate : d.generate}
                </>
              )}
            </button>
            {profile && (
              <button
                type="button"
                onClick={startEdit}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-[2px] bg-deep-violet px-3.5 py-2 text-[11px] font-bold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" className="h-3.5 w-3.5">
                  <path d="M17 3a2.83 2.83 0 114 4L7.5 20.5 2 22l1.5-5.5z" />
                </svg>
                {d.edit}
              </button>
            )}
          </div>
        )}
      </div>

      {error && (
        <p className="mx-5 mt-3 rounded-[2px] bg-coral/10 px-3 py-2 text-[12px] font-medium text-coral ring-1 ring-coral/30">
          {error}
        </p>
      )}

      {editing ? (
        <div className="space-y-3 px-5 py-4">
          <div>
            <label className="text-[10px] font-bold uppercase tracking-widest text-foreground/40">{d.summary}</label>
            <textarea
              value={form.summary ?? ""}
              onChange={(e) => setForm({ ...form, summary: e.target.value })}
              rows={3}
              placeholder={d.summaryPh}
              className="mt-1 w-full resize-none rounded-[2px] border border-card-border bg-foreground/[0.03] px-3 py-2 text-[12px] font-medium text-foreground placeholder:text-foreground/30 outline-none focus:border-deep-violet/40 focus:bg-card"
            />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {PROFILE_FIELD_META.map((f) => (
              <div key={f.key}>
                <label className="text-[10px] font-bold uppercase tracking-widest text-foreground/40">{profileFieldLabel(f.key, d.fields)}</label>
                {f.textarea ? (
                  <textarea
                    value={form[f.key] ?? ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                    rows={2}
                    placeholder={f.placeholder}
                    className="mt-1 w-full resize-none rounded-[2px] border border-card-border bg-foreground/[0.03] px-3 py-2 text-[12px] font-medium text-foreground placeholder:text-foreground/30 outline-none focus:border-deep-violet/40 focus:bg-card"
                  />
                ) : (
                  <input
                    value={form[f.key] ?? ""}
                    onChange={(e) => setForm({ ...form, [f.key]: e.target.value })}
                    placeholder={f.placeholder}
                    className="mt-1 w-full rounded-[2px] border border-card-border bg-foreground/[0.03] px-3 py-2 text-[12px] font-medium text-foreground placeholder:text-foreground/30 outline-none focus:border-deep-violet/40 focus:bg-card"
                  />
                )}
              </div>
            ))}
          </div>
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={() => setEditing(false)}
              disabled={saving}
              className="rounded-[2px] px-4 py-2 text-[12px] font-semibold text-foreground/50 transition hover:bg-foreground/[0.04] disabled:opacity-50"
            >
              {t.common.cancel}
            </button>
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={saving}
              className="inline-flex items-center gap-1.5 rounded-[2px] bg-deep-violet px-4 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
            >
              {saving && <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />}
              {d.save}
            </button>
          </div>
        </div>
      ) : loading ? (
        <div className="space-y-2 px-5 py-5">
          <div className="h-4 w-3/4 animate-pulse rounded-[2px] bg-foreground/[0.06]" />
          <div className="h-4 w-1/2 animate-pulse rounded-[2px] bg-foreground/[0.04]" />
        </div>
      ) : profile ? (
        <div className="px-5 py-4">
          {profile.summary ? (
            <p className="text-[13px] leading-relaxed text-foreground/80">{profile.summary}</p>
          ) : (
            <p className="text-[12px] italic text-foreground/35">{d.noSummary}</p>
          )}
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {PROFILE_FIELD_META.map((f) => {
              const value = (profile[f.key] as string) ?? "";
              return (
                <div key={f.key} className="rounded-[2px] bg-foreground/[0.03] px-3 py-2.5">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-foreground/35">{profileFieldLabel(f.key, d.fields)}</div>
                  <div className={`mt-0.5 text-[12px] leading-relaxed ${value ? "text-foreground/75" : "italic text-foreground/30"}`}>
                    {value || d.notSet}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-start gap-3 px-5 py-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-lg text-[12px] leading-relaxed text-foreground/50">
            {d.emptyCard}
          </p>
        </div>
      )}
    </div>
  );
}

function DatabankPageContent() {
  const { t, locale } = useI18n();
  const d = t.dashboard.databank;
  const badgeLabels = d.badge;
  const fmtDate = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleDateString(locale === "ar" ? "ar-SA" : "en-US") : "";
  const [databanks, setDatabanks] = useState<Databank[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [docs, setDocs] = useState<DatabankDoc[]>([]);
  const [docsLoading, setDocsLoading] = useState(false);
  const [processing, setProcessing] = useState<string | null>(null);
  const [previewDocId, setPreviewDocId] = useState<string | null>(null);
  const [preview, setPreview] = useState<DocumentPreview | null>(null);
  const [previewPage, setPreviewPage] = useState(1);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<string>("all");

  useEffect(() => {
    async function load() {
      try {
        const data = await listDatabanks();
        const list = Array.isArray(data) ? data : data?.databanks ?? [];
        setDatabanks(list);
        if (list.length > 0) setSelectedId((prev) => prev ?? list[0].id);
      } catch {
        setDatabanks([]);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  const selected = databanks.find((db) => db.id === selectedId) ?? null;

  function selectBank(id: string | null) {
    setSelectedId(id);
    setDocs([]);
  }

  useEffect(() => {
    if (!selectedId) return;
    const bankId = selectedId;
    let cancelled = false;
    async function loadDocs() {
      setDocsLoading(true);
      try {
        const data = await listDocuments(bankId);
        if (!cancelled) setDocs(Array.isArray(data) ? data : data?.documents ?? []);
      } catch {
        if (!cancelled) setDocs([]);
      } finally {
        if (!cancelled) setDocsLoading(false);
      }
    }
    void loadDocs();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const confirmDeleteDb = confirmDeleteId ? databanks.find((d) => d.id === confirmDeleteId) ?? null : null;

  async function confirmDelete() {
    if (!confirmDeleteId) return;
    const id = confirmDeleteId;
    setDeleting(true);
    try {
      await deleteDatabank(id);
      setDatabanks((prev) => prev.filter((db) => db.id !== id));
      if (selectedId === id) selectBank(databanks.find((d) => d.id !== id)?.id ?? null);
      setConfirmDeleteId(null);
    } catch {}
    finally {
      setDeleting(false);
    }
  }

  async function refreshDocs() {
    if (!selectedId) return;
    try {
      const data = await listDocuments(selectedId);
      setDocs(Array.isArray(data) ? data : data?.documents ?? []);
    } catch {}
  }

  async function handleRetryDoc(docId: string) {
    if (!selectedId) return;
    setProcessing(docId);
    try {
      await retryDocuments(selectedId, [docId]);
      setTimeout(() => {
        void refreshDocs().finally(() => setProcessing(null));
      }, 2000);
    } catch {
      setProcessing(null);
    }
  }

  async function handleRetryAll() {
    if (!selectedId) return;
    setProcessing("all");
    try {
      await retryDocuments(selectedId);
      setTimeout(() => {
        void refreshDocs().finally(() => setProcessing(null));
      }, 2000);
    } catch {
      setProcessing(null);
    }
  }

  const filteredDocs = useMemo(() => {
    return docs.filter((d) => {
      const name = (d.filename || d.name || "").toLowerCase();
      const matchesQ = !q || name.includes(q.toLowerCase());
      const matchesFilter = filter === "all" || d.status === filter;
      return matchesQ && matchesFilter;
    });
  }, [docs, q, filter]);

  const stuckCount = docs.filter(
    (d) => d.status === "pending" || d.status === "queued" || d.status === "processing" || d.status === "failed"
  ).length;

  const totalDocs = databanks.reduce((a, b) => a + (b.doc_count ?? 0), 0);
  const totalSize = databanks.reduce((a, b) => a + (b.total_size ?? 0), 0);
  const readyDocs = docs.filter((d) => d.status === "ready" || d.status === "completed" || d.status === "processed").length;

  async function loadPreview(docId: string, page: number) {
    if (!selectedId) return;
    setPreviewLoading(true);
    try {
      const data = await previewDocument(selectedId, docId, page, 25);
      setPreview(data);
      setPreviewDocId(docId);
      setPreviewPage(page);
    } catch {
      setPreview(null);
    } finally {
      setPreviewLoading(false);
    }
  }

  function togglePreview(docId: string) {
    if (previewDocId === docId) {
      setPreviewDocId(null);
      setPreview(null);
    } else {
      void loadPreview(docId, 1);
    }
  }

  return (
    <div className="h-full overflow-y-auto bg-background">
      <div className="space-y-6 p-4 sm:p-6">
        {/* Company Header */}
        <div className="overflow-hidden rounded-[2px] border border-card-border bg-card shadow-sm">
          <div className="bg-gradient-to-r from-deep-violet via-[#4c2a8a] to-violet-light px-6 py-5">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-4">
                <div className="flex h-11 w-11 items-center justify-center rounded-[2px] bg-white/15 text-white backdrop-blur ring-1 ring-white/20">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-6 w-6">
                    <ellipse cx="12" cy="5" rx="9" ry="3" />
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                  </svg>
                </div>
                <div>
                  <h1 className="text-[20px] font-bold tracking-tight text-white sm:text-[22px]">{d.title}</h1>
                  <p className="mt-0.5 text-[12px] font-medium text-white/70 sm:text-[13px]">
                    {d.subtitle}
                  </p>
                </div>
              </div>
              <Link
                href="/dashboard/databank/new"
                className="inline-flex items-center justify-center gap-1.5 self-start rounded-[2px] bg-white px-4 py-2.5 text-[12px] font-bold text-deep-violet shadow-sm transition hover:bg-white/90 active:scale-[0.98] sm:self-auto"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="h-3.5 w-3.5">
                  <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                </svg>
                {d.new}
              </Link>
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-[2px] bg-white/10 px-3 py-3 ring-1 ring-white/10 backdrop-blur">
                <div className="text-[10px] font-bold uppercase tracking-widest text-white/60">{d.stats.databanks}</div>
                <div className="mt-1 text-[20px] font-bold text-white">{databanks.length}</div>
              </div>
              <div className="rounded-[2px] bg-white/10 px-3 py-3 ring-1 ring-white/10 backdrop-blur">
                <div className="text-[10px] font-bold uppercase tracking-widest text-white/60">{d.stats.documents}</div>
                <div className="mt-1 text-[20px] font-bold text-white">{totalDocs}</div>
              </div>
              <div className="rounded-[2px] bg-white/10 px-3 py-3 ring-1 ring-white/10 backdrop-blur">
                <div className="text-[10px] font-bold uppercase tracking-widest text-white/60">{d.stats.storage}</div>
                <div className="mt-1 text-[20px] font-bold text-white">{formatBytes(totalSize)}</div>
              </div>
              <div className="rounded-[2px] bg-white/10 px-3 py-3 ring-1 ring-white/10 backdrop-blur">
                <div className="text-[10px] font-bold uppercase tracking-widest text-white/60">{d.stats.aiReady}</div>
                <div className="mt-1 flex items-baseline gap-1.5 text-[20px] font-bold text-white">
                  {readyDocs}
                  <span className="text-[11px] font-medium text-white/60">{fill(d.stats.inView, { count: docs.length })}</span>
                </div>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 px-6 py-3 text-[11px] font-medium text-foreground/50">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-emerald" /> {d.live.indexing}
            </span>
            <span className="text-foreground/20">•</span>
            <span>{d.live.private}</span>
            <span className="ml-auto hidden items-center gap-1 text-foreground/40 sm:inline-flex">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-3.5 w-3.5">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
              {d.live.enterprise}
            </span>
          </div>
        </div>

        {/* Business profile card — AI grounding facts, editable */}
        <BusinessProfileCard />

        {/* Business details — merchant overrides vs Google's official record */}
        <BusinessDetailsSection />

        {/* Databank Grid */}
        <div>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[13px] font-bold uppercase tracking-widest text-foreground/40">{d.yourBanks}</h2>
            <span className="text-[11px] font-medium text-foreground/30">{fill(d.total, { count: databanks.length })}</span>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {loading
              ? Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="animate-pulse rounded-[2px] border border-card-border bg-card p-5">
                    <div className="h-10 w-10 rounded-[2px] bg-foreground/[0.06]" />
                    <div className="mt-4 h-4 w-32 rounded-[2px] bg-foreground/[0.06]" />
                    <div className="mt-2 h-3 w-20 rounded-[2px] bg-foreground/[0.04]" />
                  </div>
                ))
              : databanks.map((db) => {
                  const isSelected = selectedId === db.id;
                  return (
                    <div
                      key={db.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => selectBank(isSelected ? null : db.id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          selectBank(isSelected ? null : db.id);
                        }
                      }}
                      className={[
                        "group relative overflow-hidden rounded-[2px] border bg-card p-5 text-left transition-all",
                        isSelected
                          ? "border-deep-violet shadow-lg shadow-deep-violet/10 ring-1 ring-deep-violet/10"
                          : "border-card-border hover:border-deep-violet/20 hover:shadow-md",
                      ].join(" ")}
                    >
                      {isSelected && <div className="absolute inset-x-0 top-0 h-1 bg-deep-violet" />}
                      <div className="flex items-start justify-between gap-3">
                        <div
                          className="flex h-11 w-11 items-center justify-center rounded-[2px] text-white shadow-sm"
                          style={{ backgroundColor: db.accent_color || "var(--color-deep-violet)" }}
                        >
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-5 w-5">
                            <ellipse cx="12" cy="5" rx="9" ry="3" />
                            <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                          </svg>
                        </div>
                        <div className="flex items-center gap-1">
                          {isSelected && (
                            <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-deep-violet text-white">
                              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3 w-3">
                                <path d="M5 12l7 7 7-7" strokeLinecap="round" strokeLinejoin="round" />
                              </svg>
                            </span>
                          )}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDeleteId(db.id);
                            }}
                            className="rounded-[2px] p-1.5 text-foreground/20 opacity-0 transition hover:bg-coral/10 hover:text-coral group-hover:opacity-100"
                            title={d.deleteAria}
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5">
                              <path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6M10 11v6M14 11v6" />
                            </svg>
                          </button>
                        </div>
                      </div>
                      <div className="mt-4 text-[15px] font-bold leading-tight text-foreground">{db.name}</div>
                      <div className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-foreground/50">
                        {db.description || d.noDesc}
                      </div>
                      <div className="mt-4 flex items-center gap-2">
                        <span className="inline-flex items-center gap-1 rounded-[2px] bg-foreground/[0.06] px-2.5 py-1 text-[11px] font-semibold text-foreground/60">
                          <span className="h-1.5 w-1.5 rounded-full bg-deep-violet" />
                          {fill(d.docs, { count: db.doc_count ?? 0 })}
                        </span>
                        <span className="text-[11px] font-medium text-foreground/30">{formatBytes(db.total_size ?? 0)}</span>
                        {isSelected && <span className="ml-auto text-[11px] font-bold text-deep-violet">{d.selected}</span>}
                      </div>
                    </div>
                  );
                })}
          </div>
        </div>

        {!loading && databanks.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-[2px] border-2 border-dashed border-deep-violet/15 bg-card px-6 py-16 text-center shadow-sm">
            <div className="flex h-16 w-16 items-center justify-center rounded-[2px] bg-gradient-to-br from-deep-violet to-violet-light text-white shadow-lg shadow-deep-violet/20">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-8 w-8">
                <ellipse cx="12" cy="5" rx="9" ry="3" />
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
              </svg>
            </div>
            <h2 className="mt-5 text-[18px] font-bold tracking-tight text-foreground">{d.emptyTitle}</h2>
            <p className="mt-2 max-w-md text-[13px] leading-relaxed text-foreground/50">
              {d.emptyDesc}
            </p>
            <Link
              href="/dashboard/databank/new"
              className="mt-6 inline-flex items-center gap-1.5 rounded-[2px] bg-deep-violet px-6 py-2.5 text-[13px] font-bold text-white shadow-md shadow-deep-violet/20 transition hover:bg-deep-violet/90 active:scale-[0.98]"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="h-4 w-4">
                <path d="M12 5v14M5 12h14" strokeLinecap="round" />
              </svg>
              {d.createFirst}
            </Link>
          </div>
        )}

        {/* Selected databank detail */}
        {selected && (
          <div className="overflow-hidden rounded-[2px] border border-card-border bg-card shadow-sm">
            <div className="flex flex-col gap-3 border-b border-card-border bg-foreground/[0.02] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <div
                  className="flex h-10 w-10 items-center justify-center rounded-[2px] text-white shadow-sm"
                  style={{ backgroundColor: selected.accent_color || "var(--color-deep-violet)" }}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="h-5 w-5">
                    <ellipse cx="12" cy="5" rx="9" ry="3" />
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                  </svg>
                </div>
                <div>
                  <h2 className="text-[16px] font-bold leading-tight text-foreground">{selected.name}</h2>
                  {selected.description && <p className="text-[12px] text-foreground/50">{selected.description}</p>}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className="hidden items-center gap-1.5 rounded-[2px] bg-emerald/10 px-3 py-1 text-[11px] font-bold text-emerald ring-1 ring-emerald/30 sm:inline-flex">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald" /> {d.detail.live}
                </span>
                <Link
                  href="/dashboard/databank/new"
                  className="inline-flex items-center gap-1.5 rounded-[2px] bg-deep-violet px-3.5 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-deep-violet/90"
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3.5 w-3.5">
                    <path d="M12 5v14M5 12h14" strokeLinecap="round" />
                  </svg>
                  {d.detail.addSource}
                </Link>
              </div>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 divide-x divide-card-border border-b border-card-border bg-foreground/[0.015]">
              <div className="px-5 py-4">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-foreground/40">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-3 w-3">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                    <path d="M14 2v6h6" />
                  </svg>
                  {d.detail.documents}
                </div>
                <div className="mt-1 text-[22px] font-bold tracking-tight text-foreground">{selected.doc_count ?? docs.length}</div>
              </div>
              <div className="px-5 py-4">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-foreground/40">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="h-3 w-3">
                    <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                    <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                  </svg>
                  {d.detail.storage}
                </div>
                <div className="mt-1 text-[22px] font-bold tracking-tight text-foreground">{formatBytes(selected.total_size ?? 0)}</div>
              </div>
              <div className="px-5 py-4">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-foreground/40">
                  <span className="h-2 w-2 rounded-full bg-emerald" /> {d.detail.aiSearch}
                </div>
                <div className="mt-1 text-[13px] font-bold">
                  {docs.some((x) => x.status === "completed" || x.status === "ready") ? (
                    <span className="text-emerald">{d.detail.active}</span>
                  ) : docsLoading ? (
                    <span className="text-foreground/40">{d.detail.checking}</span>
                  ) : (
                    <span className="text-foreground/40">{d.detail.noData}</span>
                  )}
                </div>
              </div>
            </div>

            {/* Toolbar */}
            <div className="flex flex-col gap-3 border-b border-card-border bg-card px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-1 items-center gap-2">
                <div className="relative flex-1 sm:max-w-xs">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-foreground/30">
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
                  </svg>
                  <input
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder={d.detail.searchPh}
                    className="w-full rounded-[2px] border border-card-border bg-foreground/[0.03] py-2 pl-8 pr-3 text-[12px] font-medium text-foreground placeholder:text-foreground/30 outline-none transition focus:border-deep-violet/30 focus:bg-card"
                  />
                </div>
                <select
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  className="rounded-[2px] border border-card-border bg-card px-2.5 py-2 text-[12px] font-semibold text-foreground/60 outline-none focus:border-deep-violet/30"
                >
                  <option value="all">{d.detail.statuses.all}</option>
                  <option value="ready">{d.detail.statuses.ready}</option>
                  <option value="processing">{d.detail.statuses.processing}</option>
                  <option value="pending">{d.detail.statuses.pending}</option>
                  <option value="failed">{d.detail.statuses.failed}</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <span className="hidden text-[11px] font-medium text-foreground/40 sm:block">
                  {fill(d.detail.of, { a: filteredDocs.length, b: docs.length })}
                </span>
                {stuckCount > 0 && (
                  <button
                    type="button"
                    onClick={() => void handleRetryAll()}
                    disabled={processing === "all"}
                    className="inline-flex items-center gap-1.5 rounded-[2px] bg-deep-violet px-3.5 py-2 text-[11px] font-bold text-white shadow-sm transition hover:bg-deep-violet/90 disabled:opacity-50"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
                      <path d="M21 12a9 9 0 11-9-9" strokeLinecap="round" />
                      <path d="M9 9l3-3 3 3M9 15l3 3 3-3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {processing === "all" ? d.detail.retrying : fill(d.detail.retry, { count: stuckCount })}
                  </button>
                )}
              </div>
            </div>

            {/* Table */}
            {docsLoading ? (
              <div className="space-y-2 p-4">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="h-14 animate-pulse rounded-[2px] bg-foreground/[0.04]" />
                ))}
              </div>
            ) : filteredDocs.length === 0 ? (
              <div className="flex flex-col items-center px-6 py-12 text-center">
                <div className="flex h-12 w-12 items-center justify-center rounded-[2px] bg-foreground/[0.04] text-foreground/20">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-6 w-6">
                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M14 2v6h6" />
                  </svg>
                </div>
                <p className="mt-3 text-[13px] font-semibold text-foreground/60">
                  {q || filter !== "all" ? d.detail.noMatch : d.detail.noDocs}
                </p>
                <p className="mt-1 max-w-sm text-[12px] leading-relaxed text-foreground/35">
                  {q || filter !== "all" ? d.detail.trySearch : d.detail.uploadCsv}
                </p>
                {!q && filter === "all" && (
                  <Link href="/dashboard/databank/new" className="mt-4 inline-flex items-center gap-1.5 rounded-[2px] bg-accent-soft px-4 py-2 text-[12px] font-bold text-deep-violet transition hover:bg-deep-violet/15 dark:text-violet-light">
                    {d.detail.addFirst}
                  </Link>
                )}
              </div>
            ) : (
              <div className="overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-card-border bg-foreground/[0.02] text-left">
                        <th className="px-4 py-2.5 text-[10px] font-bold uppercase tracking-widest text-foreground/40">{d.detail.file}</th>
                        <th className="hidden px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-foreground/40 sm:table-cell">{d.detail.type}</th>
                        <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-foreground/40">{d.detail.size}</th>
                        <th className="px-3 py-2.5 text-[10px] font-bold uppercase tracking-widest text-foreground/40">{d.detail.status}</th>
                        <th className="px-4 py-2.5 text-right text-[10px] font-bold uppercase tracking-widest text-foreground/40">{d.detail.actions}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-card-border">
                      {filteredDocs.map((doc) => (
                        <Fragment key={doc.id}>
                          <tr className="group transition hover:bg-foreground/[0.015]">
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-3">
                                <FileIcon type={doc.file_type} />
                                <div className="min-w-0">
                                  <div className="truncate text-[12px] font-semibold text-foreground">{doc.filename || doc.name || doc.id}</div>
                                  <div className="text-[11px] text-foreground/35 sm:hidden">{doc.file_type || "—"} · {formatBytes(doc.file_size ?? 0)}</div>
                                </div>
                              </div>
                            </td>
                            <td className="hidden px-3 py-3 sm:table-cell">
                              <span className="inline-flex rounded-[2px] bg-foreground/[0.06] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-foreground/50">
                                {doc.file_type || "—"}
                              </span>
                            </td>
                            <td className="px-3 py-3 text-[12px] font-medium tabular-nums text-foreground/50">{formatBytes(doc.file_size ?? 0)}</td>
                            <td className="px-3 py-3">
                              <StatusBadge status={doc.status} labels={badgeLabels} />
                            </td>
                            <td className="px-4 py-3">
                              <div className="flex items-center justify-end gap-1">
                                <button
                                  type="button"
                                  onClick={() => togglePreview(doc.id)}
                                  className={`rounded-[2px] px-2.5 py-1 text-[11px] font-semibold transition ${previewDocId === doc.id ? "bg-foreground text-background" : "border border-card-border bg-card text-foreground/60 hover:bg-foreground/[0.04]"}`}
                                >
                                  {previewDocId === doc.id ? d.detail.hide : d.detail.view}
                                </button>
                                {(doc.status === "pending" || doc.status === "queued" || doc.status === "processing" || doc.status === "failed") && (
                                  <button
                                    type="button"
                                    onClick={() => void handleRetryDoc(doc.id)}
                                    disabled={processing === doc.id}
                                    className="rounded-[2px] bg-accent-soft px-2.5 py-1 text-[11px] font-bold text-deep-violet transition hover:bg-deep-violet/15 disabled:opacity-50 dark:text-violet-light"
                                  >
                                    {processing === doc.id ? "…" : d.detail.retryShort}
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {previewDocId === doc.id && (
                            <tr className="bg-foreground/[0.015]">
                              <td colSpan={5} className="px-4 py-4">
                                {previewLoading ? (
                                  <div className="space-y-2">
                                    {Array.from({ length: 3 }).map((_, i) => (
                                      <div key={i} className="h-10 animate-pulse rounded-[2px] bg-foreground/[0.05]" />
                                    ))}
                                  </div>
                                ) : !preview ? (
                                  <p className="py-2 text-center text-[12px] text-foreground/40">{d.detail.previewFail}</p>
                                ) : preview.kind === "table" ? (
                                  <div className="overflow-hidden rounded-[2px] border border-card-border bg-card shadow-sm">
                                    <div className="flex items-center justify-between border-b border-card-border bg-foreground/[0.02] px-3 py-2">
                                      <span className="text-[11px] font-bold text-foreground/60">
                                        {fill(d.detail.rowsCols, { rows: preview.total, cols: preview.columns?.length ?? 0 })}
                                      </span>
                                      <span className="text-[11px] font-medium text-foreground/30">{fill(d.detail.page, { page: previewPage })}</span>
                                    </div>
                                    <div className="overflow-x-auto">
                                      <table className="w-full text-[12px]">
                                        <thead>
                                          <tr className="border-b border-card-border bg-foreground/[0.03]">
                                            {(preview.columns ?? []).map((col) => (
                                              <th key={col} className="whitespace-nowrap px-3 py-2 text-left text-[11px] font-bold text-foreground/60">
                                                {col}
                                              </th>
                                            ))}
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {(preview.rows ?? []).map((row, ri) => (
                                            <tr key={ri} className="border-b border-foreground/[0.04] last:border-0 hover:bg-foreground/[0.015]">
                                              {(preview.columns ?? []).map((col) => (
                                                <td key={col} className="max-w-[200px] truncate px-3 py-2 text-foreground/70">
                                                  {row[col] ?? ""}
                                                </td>
                                              ))}
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                    {preview.total > preview.page_size && (
                                      <div className="flex items-center justify-between border-t border-card-border bg-foreground/[0.015] px-3 py-2">
                                        <button
                                          type="button"
                                          disabled={previewPage <= 1 || previewLoading}
                                          onClick={() => void loadPreview(doc.id, previewPage - 1)}
                                          className="rounded-[2px] border border-card-border bg-card px-3 py-1.5 text-[11px] font-semibold text-foreground/60 transition hover:bg-foreground/[0.03] disabled:opacity-30"
                                        >
                                          {d.detail.prev}
                                        </button>
                                        <span className="text-[11px] font-medium text-foreground/40">
                                          {fill(d.detail.pageOf, { page: previewPage, total: Math.ceil(preview.total / preview.page_size) })}
                                        </span>
                                        <button
                                          type="button"
                                          disabled={previewPage >= Math.ceil(preview.total / preview.page_size) || previewLoading}
                                          onClick={() => void loadPreview(doc.id, previewPage + 1)}
                                          className="rounded-[2px] border border-card-border bg-card px-3 py-1.5 text-[11px] font-semibold text-foreground/60 transition hover:bg-foreground/[0.03] disabled:opacity-30"
                                        >
                                          {d.detail.next}
                                        </button>
                                      </div>
                                    )}
                                  </div>
                                ) : (
                                  <div className="rounded-[2px] border border-card-border bg-card p-4 shadow-sm">
                                    <p className="mb-3 text-[11px] font-bold uppercase tracking-wide text-foreground/40">
                                      {fill(d.detail.chunks, { count: preview.total })}
                                    </p>
                                    <div className="space-y-2">
                                      {(preview.chunks ?? []).map((c, i) => (
                                        <p key={i} className="rounded-[2px] bg-foreground/[0.03] px-3 py-2.5 text-[12px] leading-relaxed text-foreground/65">
                                          {c}
                                        </p>
                                      ))}
                                      {(preview.chunks ?? []).length === 0 && (
                                        <p className="py-2 text-center text-[12px] text-foreground/40">{d.detail.noChunks}</p>
                                      )}
                                    </div>
                                  </div>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Delete confirmation — destructive */}
      {confirmDeleteId && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label={d.deleteModal.aria}
          className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm"
          onClick={() => !deleting && setConfirmDeleteId(null)}
        >
          <div
            className="w-full max-w-md rounded-[2px] border border-card-border bg-card p-5 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-[2px] bg-coral/10 text-coral">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-5 w-5">
                <path d="M12 9v6M12 17h.01M10.3 3.3l-7 12A2 2 0 005 18h14a2 2 0 001.7-3l-7-12a2 2 0 00-3.4 0z" />
              </svg>
            </div>
            <h2 className="mt-3 text-[15px] font-bold text-foreground">
              {fill(d.deleteModal.title, { name: confirmDeleteDb?.name ?? "databank" })}
            </h2>
            <p className="mt-2 text-[13px] leading-relaxed text-foreground/60">
              {d.deleteModal.desc}
            </p>
            {confirmDeleteDb && (confirmDeleteDb.doc_count ?? 0) > 0 && (
              <p className="mt-2 rounded-[2px] bg-amber/10 px-3 py-2 text-[11px] font-medium text-amber ring-1 ring-amber/30">
                {(confirmDeleteDb.doc_count ?? 0) === 1
                  ? fill(d.deleteModal.lostOne, { count: confirmDeleteDb.doc_count ?? 0, size: formatBytes(confirmDeleteDb.total_size ?? 0) })
                  : fill(d.deleteModal.lostMany, { count: confirmDeleteDb.doc_count ?? 0, size: formatBytes(confirmDeleteDb.total_size ?? 0) })}
              </p>
            )}
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setConfirmDeleteId(null)}
                disabled={deleting}
                className="rounded-[2px] px-4 py-2 text-[12px] font-semibold text-foreground/60 transition hover:bg-foreground/[0.04] disabled:opacity-50"
              >
                {t.common.cancel}
              </button>
              <button
                onClick={() => void confirmDelete()}
                disabled={deleting}
                className="inline-flex items-center gap-1.5 rounded-[2px] bg-coral px-4 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-coral/90 disabled:opacity-50"
              >
                {deleting ? (
                  <>
                    <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    {d.deleteModal.deleting}
                  </>
                ) : (
                  d.deleteModal.delete
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function DatabankPage() {
  return (
    <FeatureLock feature="databank">
      <DatabankPageContent />
    </FeatureLock>
  );
}
