import Link from "next/link";
import type { AiVisibilityAction } from "@/lib/api-ai-visibility";

export default function FixNextActions({
  actions,
  label,
}: {
  actions: AiVisibilityAction[];
  label: string;
}) {
  if (actions.length === 0) return null;
  return (
    <section aria-label={label} className="divide-y divide-[var(--ai-line)] border-y border-[var(--ai-line)]">
      {actions.map((action, index) => (
        <article
          key={`${action.title}-${index}`}
          className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-3 py-4"
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-[var(--ai-radius-control)] border border-[var(--ai-line-strong)] bg-[var(--ai-sunken)] font-mono text-[12px] font-bold text-[var(--ai-accent)]">
            {String(index + 1).padStart(2, "0")}
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[9px] font-bold tracking-wide text-[var(--ai-signal)]">
                {action.priority}
              </span>
              <span className="text-[9px] font-bold uppercase tracking-[0.12em] text-[var(--ai-muted)]">
                {action.category.replaceAll("_", " ")}
              </span>
              <span className="text-[9px] text-[var(--ai-muted)]">· {action.effort}</span>
            </div>
            <h4 className="mt-1.5 text-[13px] font-bold leading-5">
              <Link
                href={action.deep_link}
                className="text-[var(--ai-accent)] underline decoration-[var(--ai-line-strong)] underline-offset-4 hover:decoration-[var(--ai-accent)]"
              >
                {action.title}
              </Link>
            </h4>
            <p className="mt-1 max-w-2xl text-[12px] leading-5 text-[var(--ai-ink-2)]">
              {action.rationale}
            </p>
          </div>
        </article>
      ))}
    </section>
  );
}
