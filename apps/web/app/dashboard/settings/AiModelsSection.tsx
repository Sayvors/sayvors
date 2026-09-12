"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch } from "@/lib/api-rag";

interface CatalogModel {
  id: string;
  name: string;
  provider: string;
  available: boolean;
  key_source: string;
}

const PROVIDER_DOT: Record<string, string> = {
  groq: "bg-orange-500",
  openai: "bg-zinc-800",
  gemini: "bg-sky-500",
  grok: "bg-black",
  kimi: "bg-zinc-500",
  deepseek: "bg-blue-600",
  ollama: "bg-pink-500",
};

export default function AiModelsSection() {
  const [models, setModels] = useState<CatalogModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/llm/models");
        if (!cancelled) {
          setModels(data.models ?? []);
          setFailed(false);
        }
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const available = models.filter((m) => m.available);

  return (
    <section className="rounded-xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink">
      <h3 className="text-[14px] font-bold text-ink dark:text-fog">AI models</h3>
      <p className="mt-0.5 text-[12px] text-ink/45 dark:text-fog/45">
        Models your administrator has enabled for your workspace. Pick a reply model per location in{" "}
        <Link href="/dashboard/automations" className="font-semibold text-deep-violet hover:underline">
          Automations
        </Link>
        .
      </p>
      {loading ? (
        <div className="mt-3 space-y-2" aria-hidden>
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-9 animate-pulse rounded-lg bg-ink/[0.05] dark:bg-fog/[0.05]" />
          ))}
        </div>
      ) : failed ? (
        <p className="mt-3 text-[12px] text-ink/40 dark:text-fog/40">
          Couldn&apos;t load the model catalog. Check that the API is running.
        </p>
      ) : available.length === 0 ? (
        <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-[12px] font-medium text-amber-700">
          No models enabled for your workspace yet — ask your administrator.
        </p>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {available.map((m) => (
            <li
              key={m.id}
              className="flex items-center gap-2.5 rounded-lg bg-ink/[0.02] px-3 py-2 dark:bg-fog/[0.03]"
            >
              <span
                aria-hidden
                className={`h-2.5 w-2.5 shrink-0 rounded-full ${PROVIDER_DOT[m.provider] ?? "bg-ink/20"}`}
              />
              <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink dark:text-fog">
                {m.name}
                <span className="ml-2 text-[11px] font-normal text-ink/35 dark:text-fog/35">{m.id}</span>
              </span>
              <span className="shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700">
                Ready
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
