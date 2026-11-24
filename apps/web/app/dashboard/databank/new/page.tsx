"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  createCrawlSource,
  createDatabank,
  previewCrawl,
  type CrawlPreviewItem,
  uploadFile,
} from "@/lib/api-rag";
import { getEntitlements } from "@/lib/api-billing";
import { useI18n } from "@/lib/i18n/I18nProvider";

type SourceType = "files" | "crawler" | "empty";

function fill(s: string, vars: Record<string, string | number>): string {
  return Object.entries(vars).reduce(
    (out, [k, v]) => out.replaceAll(`{${k}}`, String(v)),
    s,
  );
}

function normalizeCrawlerUrl(raw: string): string {
  const v = raw.trim();
  if (!v) return "";
  if (/^[a-zA-Z][a-zA-Z\d+\-.]*:\/\//.test(v)) return v;
  // Looks like a domain/path without scheme — default to https.
  if (/^[^\s/]+\.[^\s]+/.test(v) || v.startsWith("localhost")) {
    return `https://${v}`;
  }
  return v;
}

function validateCrawlerUrl(raw: string): { normalized: string; error: string | null } {
  const trimmed = raw.trim();
  if (!trimmed) {
    return { normalized: "", error: "empty" };
  }
  if (/\s/.test(trimmed)) {
    return { normalized: trimmed, error: "spaces" };
  }
  const normalized = normalizeCrawlerUrl(trimmed);
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    return { normalized, error: "invalid" };
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { normalized, error: "protocol" };
  }
  if (!parsed.hostname) {
    return { normalized, error: "host" };
  }
  // Require a dot in hostname (public domain) unless it's localhost (dev).
  if (!parsed.hostname.includes(".") && parsed.hostname !== "localhost") {
    return { normalized, error: "host" };
  }
  return { normalized: parsed.toString(), error: null };
}

export default function CreateDatabankPage() {
  const router = useRouter();
  const { t } = useI18n();
  const u = t.dashboard.databank.create;
  const STEPS = [
    { id: 1, label: u.steps.details },
    { id: 2, label: u.steps.source },
    { id: 3, label: u.steps.configure },
    { id: 4, label: u.steps.review },
  ] as const;
  // Website crawling is Enterprise-only. The API enforces this too; hiding
  // the card avoids offering a path that would 403 on the first preview.
  const [crawlerAllowed, setCrawlerAllowed] = useState(false);
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sourceType, setSourceType] = useState<SourceType | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [crawlerUrl, setCrawlerUrl] = useState("");
  const [urlTouched, setUrlTouched] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<CrawlPreviewItem[]>([]);
  const [selectedUrls, setSelectedUrls] = useState<Set<string>>(new Set());
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let alive = true;
    void getEntitlements()
      .then((ent) => {
        if (!alive) return;
        const allowed = ent.features?.crawler === true;
        setCrawlerAllowed(allowed);
        if (!allowed) setSourceType((current) => (current === "crawler" ? null : current));
      })
      .catch(() => {
        // Fail closed: an unreadable entitlement must never expose the gate.
        if (alive) setCrawlerAllowed(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const urlValidation = useMemo(() => validateCrawlerUrl(crawlerUrl), [crawlerUrl]);
  const urlErrorMessage = useMemo(() => {
    if (!urlTouched || !crawlerUrl.trim()) return null;
    if (!urlValidation.error) return null;
    const msg =
      u.urlErrors?.[urlValidation.error as keyof typeof u.urlErrors] ??
      u.previewFailed;
    return msg;
  }, [crawlerUrl, u, urlTouched, urlValidation.error]);

  const canPreview = urlValidation.error === null && !previewLoading;

  const canProceed = useMemo(() => {
    if (step === 1) return name.trim().length > 0;
    if (step === 2) return sourceType !== null;
    if (step === 3) {
      if (sourceType === "files") return files.length > 0;
      if (sourceType === "crawler") return selectedUrls.size > 0;
      return true;
    }
    return true;
  }, [files.length, name, selectedUrls.size, sourceType, step]);

  const sourceLabels: Record<SourceType, string> = {
    files: u.sources.files,
    crawler: u.sources.crawler,
    empty: u.sources.empty,
  };
  const currentSourceLabel = sourceType ? sourceLabels[sourceType] : u.notSelected;

  const handlePreview = async () => {
    setUrlTouched(true);
    const { normalized, error } = validateCrawlerUrl(crawlerUrl);
    if (error) {
      setCandidates([]);
      setSelectedUrls(new Set());
      return;
    }
    if (normalized !== crawlerUrl) setCrawlerUrl(normalized);
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const data = await previewCrawl(normalized, "subtree", 100);
      setCandidates(data.candidates);
      setSelectedUrls(new Set(data.candidates.map((c) => c.url)));
    } catch (e) {
      setCandidates([]);
      setSelectedUrls(new Set());
      setPreviewError(e instanceof Error && e.message ? e.message : u.previewFailed);
    } finally {
      setPreviewLoading(false);
    }
  };

  const toggleUrl = (url: string, checked: boolean) => {
    setSelectedUrls((prev) => {
      const next = new Set(prev);
      if (checked) next.add(url);
      else next.delete(url);
      return next;
    });
  };

  const handleNext = () => {
    if (canProceed && step < STEPS.length) setStep((prev) => prev + 1);
  };

  const handleBack = () => {
    if (step > 1) setStep((prev) => prev - 1);
  };

  const handleCreate = async () => {
    if (!sourceType) return;
    setIsSubmitting(true);

    try {
      const created = await createDatabank({
        name: name.trim(),
        description: description.trim() || undefined,
      });

      if (sourceType === "files" && files.length) {
        for (const file of files) {
          await uploadFile(created.id, file);
        }
      }

      if (sourceType === "crawler" && selectedUrls.size > 0) {
        const { normalized } = validateCrawlerUrl(crawlerUrl);
        await createCrawlSource(created.id, {
          url: normalized || crawlerUrl.trim(),
          scope: "subtree",
          max_pages: Math.max(1, selectedUrls.size),
          urls: Array.from(selectedUrls),
          sync_enabled: false,
        });
      }

      router.push("/dashboard/databank");
    } catch (error) {
      console.error("Failed to create databank", error);
      alert(u.createFailed);
    } finally {
      setIsSubmitting(false);
    }
  };

  const progressPct = ((step - 1) / (STEPS.length - 1)) * 100;

  return (
    <div className="min-h-full bg-[#f8f6ff]">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <nav className="mb-3 flex items-center gap-2 text-[12px] font-medium text-ink/50">
              <Link href="/dashboard/databank" className="transition hover:text-deep-violet">
                {u.breadcrumbDatabank}
              </Link>
              <span aria-hidden="true">/</span>
              <span className="text-ink/80">{u.breadcrumbCreate}</span>
            </nav>
            <h1 className="text-[28px] font-black tracking-tight text-ink sm:text-[32px]">
              {u.title}
            </h1>
            <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-ink/55">
              {u.subtitle ?? "Set up a knowledge source your assistant can search and cite."}
            </p>
          </div>

          <Link
            href="/dashboard/databank"
            className="inline-flex items-center justify-center rounded-[8px] border border-ink/10 bg-white px-4 py-2.5 text-[13px] font-semibold text-ink/70 shadow-[0_1px_0_rgba(20,16,31,0.04)] transition hover:border-deep-violet/20 hover:text-deep-violet"
          >
            {u.backList}
          </Link>
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.35fr)_340px]">
          <div className="rounded-[8px] border border-ink/[0.06] bg-white p-5 shadow-[0_18px_44px_-30px_rgba(61,29,110,0.35)] sm:p-7">
            {/* Stepper */}
            <div className="mb-8">
              <div className="relative">
                <div className="absolute left-0 right-0 top-5 h-[2px] rounded-full bg-ink/[0.08]" aria-hidden="true" />
                <div
                  className="absolute left-0 top-5 h-[2px] rounded-full bg-deep-violet transition-all duration-300"
                  style={{ width: `${progressPct}%` }}
                  aria-hidden="true"
                />
                <ol className="relative z-10 grid grid-cols-4 gap-2">
                  {STEPS.map((item) => {
                    const isActive = step === item.id;
                    const isDone = step > item.id;
                    return (
                      <li key={item.id} className="flex flex-col items-center text-center">
                        <button
                          type="button"
                          onClick={() => {
                            if (isDone) setStep(item.id);
                          }}
                          disabled={!isDone}
                          className={[
                            "flex h-10 w-10 items-center justify-center rounded-full border-2 text-[13px] font-bold transition",
                            isActive
                              ? "border-deep-violet bg-deep-violet text-white shadow-[0_8px_18px_-10px_rgba(61,29,110,0.9)]"
                              : isDone
                                ? "border-deep-violet/20 bg-deep-violet/[0.08] text-deep-violet hover:bg-deep-violet/[0.12]"
                                : "border-ink/[0.08] bg-white text-ink/35",
                            isDone ? "cursor-pointer" : "cursor-default",
                          ].join(" ")}
                          aria-current={isActive ? "step" : undefined}
                        >
                          {isDone ? (
                            <svg viewBox="0 0 20 20" fill="currentColor" className="h-4 w-4" aria-hidden="true">
                              <path
                                fillRule="evenodd"
                                d="M16.704 5.29a1 1 0 010 1.415l-7.2 7.2a1 1 0 01-1.414 0l-3.2-3.2a1 1 0 111.414-1.414l2.493 2.493 6.493-6.494a1 1 0 011.414 0z"
                                clipRule="evenodd"
                              />
                            </svg>
                          ) : (
                            item.id
                          )}
                        </button>
                        <span
                          className={[
                            "mt-2 text-[11px] font-semibold leading-tight sm:text-[12px]",
                            isActive ? "text-ink" : isDone ? "text-deep-violet" : "text-ink/40",
                          ].join(" ")}
                        >
                          {item.label}
                        </span>
                      </li>
                    );
                  })}
                </ol>
              </div>
            </div>

            <div className="min-h-[380px]">
              {step === 1 && (
                <section className="space-y-5">
                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-deep-violet/70">
                      {u.detailsTitle}
                    </p>
                    <h2 className="mt-1 text-[20px] font-bold text-ink">{u.steps.details}</h2>
                  </div>
                  <div className="space-y-4">
                    <div>
                      <label className="mb-1.5 block text-[12px] font-semibold text-ink/70">
                        {u.name} <span className="text-coral">*</span>
                      </label>
                      <input
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder={u.namePh}
                        className="w-full rounded-[8px] border border-ink/10 bg-[#fbfaff] px-4 py-3 text-[14px] text-ink placeholder:text-ink/30 outline-none transition focus:border-deep-violet/40 focus:bg-white focus:ring-4 focus:ring-deep-violet/[0.08]"
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-[12px] font-semibold text-ink/70">
                        {u.description}
                      </label>
                      <textarea
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        rows={5}
                        placeholder={u.descriptionPh}
                        className="w-full resize-y rounded-[8px] border border-ink/10 bg-[#fbfaff] px-4 py-3 text-[14px] text-ink placeholder:text-ink/30 outline-none transition focus:border-deep-violet/40 focus:bg-white focus:ring-4 focus:ring-deep-violet/[0.08]"
                      />
                    </div>
                  </div>
                </section>
              )}

              {step === 2 && (
                <section className="space-y-5">
                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-deep-violet/70">
                      {u.steps.source}
                    </p>
                    <h2 className="mt-1 text-[20px] font-bold text-ink">{u.chooseSource}</h2>
                  </div>
                  <div className="grid gap-3">
                    {([
                      {
                        value: "files" as const,
                        title: u.sources.files,
                        desc: u.sourceDescs.files,
                        icon: (
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m6.75 12l-3-3m0 0l-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                          />
                        ),
                      },
                      {
                        value: "crawler" as const,
                        title: u.sources.crawler,
                        desc: u.sourceDescs.crawler,
                        icon: (
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5a17.92 17.92 0 01-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418"
                          />
                        ),
                      },
                      {
                        value: "empty" as const,
                        title: u.sources.empty,
                        desc: u.sourceDescs.empty,
                        icon: (
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M12 9v6m3-3H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z"
                          />
                        ),
                      },
                    ] as const)
                      .filter((option) => option.value !== "crawler" || crawlerAllowed)
                      .map((option) => {
                      const selected = sourceType === option.value;
                      return (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => {
                            setSourceType(option.value as SourceType);
                            setSelectedUrls(new Set());
                            setCandidates([]);
                            setPreviewError(null);
                          }}
                          className={[
                            "group flex w-full items-start gap-4 rounded-[8px] border-2 p-4 text-left transition sm:p-5",
                            selected
                              ? "border-deep-violet bg-deep-violet/[0.04] shadow-[0_10px_24px_-18px_rgba(61,29,110,0.45)]"
                              : "border-ink/[0.08] bg-white hover:border-deep-violet/25 hover:bg-[#fbfaff]",
                          ].join(" ")}
                        >
                          <span
                            className={[
                              "mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-[8px] border transition",
                              selected
                                ? "border-deep-violet/20 bg-deep-violet text-white"
                                : "border-ink/[0.08] bg-ink/[0.03] text-ink/50 group-hover:text-deep-violet",
                            ].join(" ")}
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="h-5 w-5">
                              {option.icon}
                            </svg>
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center justify-between gap-3">
                              <span className="block text-[15px] font-bold text-ink">{option.title}</span>
                              <span
                                className={[
                                  "flex h-5 w-5 items-center justify-center rounded-full border-2 transition",
                                  selected ? "border-deep-violet bg-deep-violet" : "border-ink/20 bg-white",
                                ].join(" ")}
                                aria-hidden="true"
                              >
                                {selected && <span className="h-2 w-2 rounded-full bg-white" />}
                              </span>
                            </span>
                            <span className="mt-1 block text-[13px] leading-relaxed text-ink/55">
                              {option.desc}
                            </span>
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              )}

              {step === 3 && (
                <section className="space-y-5">
                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-deep-violet/70">
                      {u.steps.configure}
                    </p>
                    <h2 className="mt-1 text-[20px] font-bold text-ink">{u.configure}</h2>
                  </div>

                  {sourceType === "files" && (
                    <div className="space-y-3">
                      <label className="block text-[12px] font-semibold text-ink/70">{u.uploadFiles}</label>
                      <label className="group block cursor-pointer rounded-[8px] border-2 border-dashed border-ink/15 bg-[#fbfaff] p-8 text-center transition hover:border-deep-violet/35 hover:bg-white">
                        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-[8px] bg-deep-violet/[0.08] text-deep-violet">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="h-6 w-6">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z" />
                          </svg>
                        </div>
                        <div className="text-[14px] font-semibold text-ink/75">{u.dropHint}</div>
                        <div className="mt-1 text-[12px] text-ink/45">
                          {files.length ? fill(u.selected, { count: files.length }) : u.formats}
                        </div>
                        <input
                          type="file"
                          multiple
                          accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.xls,.sql"
                          className="hidden"
                          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                        />
                      </label>

                      {files.length > 0 && (
                        <ul className="space-y-1.5 rounded-[8px] border border-ink/[0.06] bg-white p-3">
                          {files.map((file) => (
                            <li
                              key={`${file.name}-${file.size}`}
                              className="flex items-center gap-2 truncate rounded-[8px] px-2 py-1.5 text-[13px] text-ink/70"
                            >
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet/50" />
                              <span className="truncate">{file.name}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}

                  {sourceType === "crawler" && (
                    <div className="space-y-4">
                      <div>
                        <label className="mb-1.5 block text-[12px] font-semibold text-ink/70">
                          {u.websiteUrl ?? "Website URL"} <span className="text-coral">*</span>
                        </label>
                        <div className="flex flex-col gap-2 sm:flex-row">
                          <div className="min-w-0 flex-1">
                            <input
                              type="url"
                              value={crawlerUrl}
                              onChange={(e) => {
                                setCrawlerUrl(e.target.value);
                                setCandidates([]);
                                setSelectedUrls(new Set());
                                setPreviewError(null);
                              }}
                              onBlur={() => {
                                setUrlTouched(true);
                                const { normalized, error } = validateCrawlerUrl(crawlerUrl);
                                if (!error && normalized && normalized !== crawlerUrl) {
                                  setCrawlerUrl(normalized);
                                }
                              }}
                              placeholder="https://docs.example.com"
                              inputMode="url"
                              autoCapitalize="none"
                              autoCorrect="off"
                              spellCheck={false}
                              className={[
                                "w-full rounded-[8px] border bg-[#fbfaff] px-4 py-3 text-[14px] text-ink placeholder:text-ink/30 outline-none transition focus:bg-white focus:ring-4",
                                urlErrorMessage
                                  ? "border-coral/50 focus:border-coral/60 focus:ring-coral/[0.12]"
                                  : "border-ink/10 focus:border-deep-violet/40 focus:ring-deep-violet/[0.08]",
                              ].join(" ")}
                              aria-invalid={urlErrorMessage ? true : undefined}
                              aria-describedby={urlErrorMessage ? "crawler-url-error" : undefined}
                            />
                          </div>
                          <button
                            type="button"
                            onClick={() => void handlePreview()}
                            disabled={!canPreview || !crawlerUrl.trim()}
                            className="shrink-0 rounded-[8px] bg-deep-violet px-5 py-3 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:opacity-95 active:translate-y-[1px] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                          >
                            {previewLoading ? u.previewing : u.previewBtn}
                          </button>
                        </div>
                        <p className="mt-2 text-[12px] text-ink/45">
                          {u.urlHint ?? "Use a full https:// link. We’ll discover pages on the same site so you can choose what to crawl."}
                        </p>
                        {urlErrorMessage && (
                          <p id="crawler-url-error" className="mt-2 text-[12px] font-semibold text-coral">
                            {urlErrorMessage}
                          </p>
                        )}
                      </div>

                      {previewError && (
                        <div className="rounded-[8px] border border-coral/20 bg-[#fff5f6] px-4 py-3 text-[13px] text-[#b42318]">
                          {previewError}
                        </div>
                      )}

                      {!previewLoading && candidates.length === 0 && !previewError && crawlerUrl.trim() && !urlErrorMessage && (
                        <p className="rounded-[8px] border border-ink/[0.06] bg-white px-4 py-3 text-[13px] text-ink/55">
                          {u.noPages}
                        </p>
                      )}

                      {candidates.length > 0 && (
                        <div className="overflow-hidden rounded-[8px] border border-ink/[0.08] bg-white">
                          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink/[0.06] bg-ink/[0.02] px-4 py-3">
                            <div>
                              <p className="text-[13px] font-bold text-ink">
                                {fill(u.pagesFound, { n: candidates.length })}
                              </p>
                              <p className="text-[12px] text-ink/50">
                                {fill(u.selectedCount, { n: selectedUrls.size })}
                              </p>
                            </div>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                className="rounded-full border border-ink/10 bg-white px-3 py-1.5 text-[12px] font-semibold text-ink/70 transition hover:border-deep-violet/30 hover:text-deep-violet"
                                onClick={() => setSelectedUrls(new Set(candidates.map((c) => c.url)))}
                              >
                                {u.selectAll}
                              </button>
                              <button
                                type="button"
                                className="rounded-full border border-ink/10 bg-white px-3 py-1.5 text-[12px] font-semibold text-ink/70 transition hover:border-deep-violet/30 hover:text-deep-violet"
                                onClick={() => setSelectedUrls(new Set())}
                              >
                                {u.clearAll}
                              </button>
                            </div>
                          </div>
                          <div className="max-h-72 overflow-y-auto p-2">
                            {candidates.map((c) => {
                              const checked = selectedUrls.has(c.url);
                              return (
                                <label
                                  key={c.url}
                                  className={[
                                    "flex cursor-pointer items-start gap-3 rounded-[8px] px-3 py-2.5 transition",
                                    checked ? "bg-deep-violet/[0.04]" : "hover:bg-ink/[0.02]",
                                  ].join(" ")}
                                >
                                  <input
                                    type="checkbox"
                                    checked={checked}
                                    onChange={(e) => toggleUrl(c.url, e.target.checked)}
                                    className="mt-1 h-4 w-4 rounded border-ink/20 text-deep-violet accent-deep-violet focus:ring-deep-violet/30"
                                  />
                                  <span className="min-w-0 flex-1">
                                    <span className="block truncate text-[13px] font-semibold text-ink">
                                      {c.title || c.url}
                                    </span>
                                    <span className="block truncate text-[12px] text-ink/45">{c.url}</span>
                                  </span>
                                </label>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {candidates.length > 0 && selectedUrls.size === 0 && (
                        <p className="text-[13px] font-semibold text-coral">{u.noneSelected}</p>
                      )}
                    </div>
                  )}

                  {sourceType === "empty" && (
                    <div className="rounded-[8px] border border-dashed border-ink/15 bg-[#fbfaff] p-6 text-center">
                      <p className="text-[14px] font-medium text-ink/70">{u.emptyNote}</p>
                    </div>
                  )}
                </section>
              )}

              {step === 4 && (
                <section className="space-y-5">
                  <div>
                    <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-deep-violet/70">
                      {u.steps.review}
                    </p>
                    <h2 className="mt-1 text-[20px] font-bold text-ink">{u.review}</h2>
                  </div>

                  <div className="space-y-3">
                    <div className="rounded-[8px] border border-ink/[0.08] bg-white p-5">
                      <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">{u.name}</p>
                      <p className="mt-1.5 text-[16px] font-semibold text-ink">{name || u.untitled}</p>
                      {description ? (
                        <p className="mt-2 text-[13px] leading-relaxed text-ink/60">{description}</p>
                      ) : null}
                    </div>

                    <div className="rounded-[8px] border border-ink/[0.08] bg-white p-5">
                      <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/40">{u.steps.source}</p>
                      <p className="mt-1.5 text-[15px] font-semibold text-ink">{currentSourceLabel}</p>
                      {sourceType === "files" && (
                        <p className="mt-1 text-[13px] text-ink/55">{fill(u.filesCount, { count: files.length })}</p>
                      )}
                      {sourceType === "crawler" && (
                        <div className="mt-2 space-y-1">
                          <p className="text-[13px] text-ink/60">
                            {fill(u.crawlerDetail, { url: urlValidation.normalized || crawlerUrl.trim(), count: selectedUrls.size })}
                          </p>
                          <p className="break-all text-[12px] text-ink/45">{urlValidation.normalized || crawlerUrl.trim()}</p>
                        </div>
                      )}
                      {sourceType === "empty" && (
                        <p className="mt-1 text-[13px] text-ink/55">{u.emptyNote}</p>
                      )}
                    </div>
                  </div>
                </section>
              )}
            </div>

            <div className="mt-8 flex items-center justify-between border-t border-ink/[0.06] pt-5">
              <button
                type="button"
                onClick={step === 1 ? () => router.push("/dashboard/databank") : handleBack}
                className="rounded-[8px] border border-ink/10 bg-white px-5 py-2.5 text-[13px] font-semibold text-ink/70 transition hover:border-deep-violet/20 hover:text-deep-violet"
              >
                {step === 1 ? t.common.cancel : t.common.back}
              </button>

              {step < STEPS.length ? (
                <button
                  type="button"
                  disabled={!canProceed}
                  onClick={handleNext}
                  className="rounded-[8px] bg-deep-violet px-6 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:opacity-95 active:translate-y-[1px] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  {u.continue}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleCreate()}
                  disabled={isSubmitting || !sourceType}
                  className="rounded-[8px] bg-deep-violet px-6 py-2.5 text-[13px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:opacity-95 active:translate-y-[1px] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  {isSubmitting ? u.creating : u.create}
                </button>
              )}
            </div>
          </div>

          <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
            <div className="rounded-[8px] border border-ink/[0.06] bg-white p-5 shadow-[0_18px_44px_-30px_rgba(61,29,110,0.2)]">
              <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em] text-ink/45">{u.whyTitle}</p>
              <div className="space-y-3">
                <div className="rounded-[8px] bg-[#f8f6ff] p-4">
                  <div className="mb-1 text-[13px] font-bold text-ink">{u.why.files}</div>
                  <p className="text-[13px] leading-relaxed text-ink/60">{u.why.filesDesc}</p>
                </div>
                <div className="rounded-[8px] bg-[#f8f6ff] p-4">
                  <div className="mb-1 text-[13px] font-bold text-ink">{u.why.crawler}</div>
                  <p className="text-[13px] leading-relaxed text-ink/60">{u.why.crawlerDesc}</p>
                </div>
              </div>
            </div>

            <div className="rounded-[8px] border border-ink/[0.06] bg-white p-5 shadow-[0_18px_44px_-30px_rgba(61,29,110,0.2)]">
              <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.14em] text-ink/45">{u.bestTitle}</p>
              <ul className="space-y-2.5 text-[13px] leading-relaxed text-ink/60">
                <li className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet/40" /><span>{u.best.one}</span></li>
                <li className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet/40" /><span>{u.best.two}</span></li>
                <li className="flex gap-2"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-deep-violet/40" /><span>{u.best.three}</span></li>
              </ul>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
