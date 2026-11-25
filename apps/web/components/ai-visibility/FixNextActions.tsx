import Link from "next/link";
import type { AiVisibilityAction } from "@/lib/api-ai-visibility";

export default function FixNextActions({
  actions,
}: {
  actions: AiVisibilityAction[];
}) {
  if (actions.length === 0) return null;
  return (
    <section aria-label="Fix next" className="space-y-2">
      {actions.map((action, index) => (
        <article
          key={`${action.title}-${index}`}
          className="rounded-[8px] border border-[var(--ui-line)] bg-white p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[var(--ui-sunken)] px-2 py-0.5 text-[10px] font-bold">
              {action.priority}
            </span>
            <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--ui-ink-2)]">
              {action.category.replaceAll("_", " ")}
            </span>
          </div>
          <h4 className="mt-2 text-[13px] font-bold">
            <Link
              href={action.deep_link}
              className="text-[var(--ui-ink)] underline"
            >
              {action.title}
            </Link>
          </h4>
          <p className="mt-1 text-[12px] text-[var(--ui-ink-2)]">
            {action.rationale}
          </p>
        </article>
      ))}
    </section>
  );
}
