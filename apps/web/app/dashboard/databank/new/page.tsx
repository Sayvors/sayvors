"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { createDatabank, scrapeUrl, uploadFile } from "@/lib/api-rag";

const STEPS = [
  { id: 1, label: "Details" },
  { id: 2, label: "Source" },
  { id: 3, label: "Configure" },
  { id: 4, label: "Review" },
] as const;

type SourceType = "files" | "crawler" | "database" | "empty";

export default function CreateDatabankPage() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sourceType, setSourceType] = useState<SourceType | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [crawlerUrl, setCrawlerUrl] = useState("");
  const [crawlerDepth, setCrawlerDepth] = useState(2);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const canProceed = useMemo(() => {
    if (step === 1) return name.trim().length > 0;
    if (step === 2) return sourceType !== null;
    if (step === 3) {
      if (sourceType === "files") return files.length > 0;
      if (sourceType === "crawler") return crawlerUrl.trim().length > 0;
      return true;
    }
    return true;
  }, [crawlerUrl, files.length, name, sourceType, step]);

  const currentSourceLabel = sourceType
    ? {
        files: "Upload files",
        crawler: "Web crawler",
        database: "Live database",
        empty: "Start empty",
      }[sourceType]
    : "Not selected";

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

      if (sourceType === "crawler" && crawlerUrl.trim()) {
        await scrapeUrl(created.id, crawlerUrl.trim(), "single", Math.max(1, crawlerDepth));
      }

      router.push("/dashboard/databank");
    } catch (error) {
      console.error("Failed to create databank", error);
      alert("Could not create databank. Please check the backend and try again.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-full bg-[#f4f1ff]">
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6 flex items-center justify-between gap-3">
          <div>
            <nav className="mb-2 flex items-center gap-2 text-[11px] font-medium text-ink/55">
              <Link href="/dashboard/databank" className="transition hover:text-deep-violet">
                Databank
              </Link>
              <span>/</span>
              <span className="text-ink">Create</span>
            </nav>
            <h1 className="text-[24px] font-black text-ink">Create Databank</h1>
          </div>

          <Link
            href="/dashboard/databank"
            className="rounded-xl border border-ink/10 bg-white px-3 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02]"
          >
            Back to list
          </Link>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
          <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
            <div className="mb-5 flex items-center gap-2">
              {STEPS.map((item, index) => {
                const isActive = step === item.id;
                const isDone = step > item.id;
                return (
                  <div key={item.id} className="flex flex-1 items-center gap-2">
                    <div
                      className={[
                        "flex h-8 w-8 items-center justify-center rounded-full text-[11px] font-bold transition",
                        isActive ? "bg-deep-violet text-white" : isDone ? "bg-deep-violet/10 text-deep-violet" : "bg-ink/[0.04] text-ink/45",
                      ].join(" ")}
                    >
                      {isDone ? "✓" : item.id}
                    </div>
                    <span
                      className={[
                        "hidden text-[11px] font-semibold sm:inline",
                        isActive ? "text-ink" : isDone ? "text-deep-violet" : "text-ink/45",
                      ].join(" ")}
                    >
                      {item.label}
                    </span>
                    {index < STEPS.length - 1 && <div className="hidden h-px flex-1 bg-ink/[0.08] sm:block" />}
                  </div>
                );
              })}
            </div>

            <div className="min-h-[360px] rounded-2xl bg-ink/[0.02] p-4 sm:p-5">
              {step === 1 && (
                <div className="space-y-4">
                  <div>
                    <p className="mb-2 text-[12px] font-bold uppercase tracking-[0.12em] text-ink/45">Databank details</p>
                    <label className="mb-1.5 block text-[11px] font-semibold text-ink/55">Name</label>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      placeholder="e.g. Product Knowledge Base"
                      className="w-full rounded-xl border border-ink/10 bg-white px-4 py-2.5 text-[13px] text-ink placeholder:text-ink/30 focus:border-deep-violet/40 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-[11px] font-semibold text-ink/55">Description</label>
                    <textarea
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      rows={5}
                      placeholder="What should this databank be used for?"
                      className="w-full rounded-xl border border-ink/10 bg-white px-4 py-2.5 text-[13px] text-ink placeholder:text-ink/30 focus:border-deep-violet/40 focus:outline-none"
                    />
                  </div>
                </div>
              )}

              {step === 2 && (
                <div className="space-y-3">
                  <p className="text-[12px] font-bold uppercase tracking-[0.12em] text-ink/45">Choose a source</p>
                  {[
                    { value: "files", title: "Upload files", desc: "PDFs, docs, text files, CSVs, and more" },
                    { value: "crawler", title: "Web crawler", desc: "Crawl a web page or documentation site" },
                    { value: "database", title: "Live database", desc: "Connect PostgreSQL or MySQL later" },
                    { value: "empty", title: "Start empty", desc: "Create a blank databank and add content later" },
                  ].map((option) => {
                    const selected = sourceType === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setSourceType(option.value as SourceType)}
                        className={[
                          "flex w-full items-start gap-3 rounded-2xl border p-3 text-left transition",
                          selected ? "border-deep-violet/50 bg-deep-violet/[0.04]" : "border-ink/10 bg-white hover:border-deep-violet/20",
                        ].join(" ")}
                      >
                        <span
                          className={[
                            "mt-0.5 flex h-4 w-4 items-center justify-center rounded-full border-2",
                            selected ? "border-deep-violet bg-deep-violet" : "border-ink/20 bg-white",
                          ].join(" ")}
                        >
                          {selected && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
                        </span>
                        <span>
                          <span className="block text-[13px] font-bold text-ink">{option.title}</span>
                          <span className="mt-0.5 block text-[11px] text-ink/55">{option.desc}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              {step === 3 && (
                <div className="space-y-4">
                  <p className="text-[12px] font-bold uppercase tracking-[0.12em] text-ink/45">Configure source</p>

                  {sourceType === "files" && (
                    <div>
                      <label className="mb-1.5 block text-[11px] font-semibold text-ink/55">Upload files</label>
                      <label className="block cursor-pointer rounded-2xl border-2 border-dashed border-ink/15 bg-white p-5 text-center transition hover:border-deep-violet/40">
                        <div className="text-[12px] font-semibold text-ink/70">Drop files here or click to browse</div>
                        <div className="mt-1 text-[10px] text-ink/40">
                          {files.length ? `${files.length} selected` : "PDF, DOCX, TXT, MD, CSV, XLSX, SQL"}
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
                        <ul className="mt-3 space-y-1 text-[11px] text-ink/60">
                          {files.map((file) => (
                            <li key={`${file.name}-${file.size}`} className="truncate">
                              • {file.name}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}

                  {sourceType === "crawler" && (
                    <div className="space-y-3">
                      <div>
                        <label className="mb-1.5 block text-[11px] font-semibold text-ink/55">Website URL</label>
                        <input
                          type="url"
                          value={crawlerUrl}
                          onChange={(e) => setCrawlerUrl(e.target.value)}
                          placeholder="https://docs.example.com"
                          className="w-full rounded-xl border border-ink/10 bg-white px-4 py-2.5 text-[13px] text-ink placeholder:text-ink/30 focus:border-deep-violet/40 focus:outline-none"
                        />
                      </div>

                      <div>
                        <label className="mb-1.5 block text-[11px] font-semibold text-ink/55">Crawl depth</label>
                        <input
                          type="number"
                          min={1}
                          max={5}
                          value={crawlerDepth}
                          onChange={(e) => setCrawlerDepth(Math.min(5, Math.max(1, Number(e.target.value) || 1)))}
                          className="w-full rounded-xl border border-ink/10 bg-white px-4 py-2.5 text-[13px] text-ink focus:border-deep-violet/40 focus:outline-none"
                        />
                      </div>
                    </div>
                  )}

                  {sourceType === "database" && (
                    <div className="rounded-2xl border border-dashed border-ink/15 bg-white p-4 text-[12px] text-ink/60">
                      You can connect a PostgreSQL or MySQL source after the databank is created from the database tab.
                    </div>
                  )}

                  {sourceType === "empty" && (
                    <div className="rounded-2xl border border-dashed border-ink/15 bg-white p-4 text-[12px] text-ink/60">
                      This databank will be created empty, and you can add sources later.
                    </div>
                  )}
                </div>
              )}

              {step === 4 && (
                <div className="space-y-3">
                  <p className="text-[12px] font-bold uppercase tracking-[0.12em] text-ink/45">Review</p>

                  <div className="rounded-2xl border border-ink/10 bg-white p-4">
                    <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">Name</p>
                    <p className="mt-1 text-[14px] font-semibold text-ink">{name || "Untitled databank"}</p>
                  </div>

                  {description && (
                    <div className="rounded-2xl border border-ink/10 bg-white p-4">
                      <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">Description</p>
                      <p className="mt-1 text-[12px] text-ink/70">{description}</p>
                    </div>
                  )}

                  <div className="rounded-2xl border border-ink/10 bg-white p-4">
                    <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-ink/40">Source</p>
                    <p className="mt-1 text-[12px] text-ink/70">{currentSourceLabel}</p>
                    {sourceType === "files" && <p className="mt-1 text-[11px] text-ink/50">{files.length} file(s) selected</p>}
                    {sourceType === "crawler" && <p className="mt-1 text-[11px] text-ink/50">{crawlerUrl} (depth {crawlerDepth})</p>}
                  </div>
                </div>
              )}
            </div>

            <div className="mt-5 flex items-center justify-between">
              <button
                type="button"
                onClick={step === 1 ? () => router.push("/dashboard/databank") : handleBack}
                className="rounded-xl border border-ink/10 bg-white px-4 py-2 text-[12px] font-semibold text-ink/70 transition hover:bg-ink/[0.02]"
              >
                {step === 1 ? "Cancel" : "Back"}
              </button>

              {step < STEPS.length ? (
                <button
                  type="button"
                  disabled={!canProceed}
                  onClick={handleNext}
                  className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Continue
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void handleCreate()}
                  disabled={isSubmitting || !sourceType}
                  className="rounded-xl bg-deep-violet px-4 py-2 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {isSubmitting ? "Creating..." : "Create databank"}
                </button>
              )}
            </div>
          </div>

          <aside className="space-y-4">
            <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
              <p className="mb-3 text-[12px] font-bold uppercase tracking-[0.12em] text-ink/45">Why this works</p>
              <div className="space-y-3 text-[12px] text-ink/65">
                <div className="rounded-2xl bg-ink/[0.02] p-3">
                  <div className="mb-1 font-bold text-ink">Upload files</div>
                  Best for PDFs, SOPs, manuals, and reference docs you want indexed immediately.
                </div>
                <div className="rounded-2xl bg-ink/[0.02] p-3">
                  <div className="mb-1 font-bold text-ink">Web crawler</div>
                  Great for docs, knowledge bases, and help centers that change over time.
                </div>
                <div className="rounded-2xl bg-ink/[0.02] p-3">
                  <div className="mb-1 font-bold text-ink">Database</div>
                  Use a live data source when your answers should reflect current records.
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-white bg-white/80 p-5 shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
              <p className="mb-2 text-[12px] font-bold uppercase tracking-[0.12em] text-ink/45">Best practices</p>
              <ul className="space-y-2 text-[12px] text-ink/65">
                <li>• Use a clear name that matches the subject matter.</li>
                <li>• Keep the description specific so future teammates know what it contains.</li>
                <li>• Start with a tight source set; large crawls can be noisy.</li>
              </ul>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
