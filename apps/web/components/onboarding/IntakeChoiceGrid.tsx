"use client";

/* Grid of large, tappable answer cards.
 *
 * The old intake used small pill chips, which made ten questions look like one
 * wall of noise. This is the same choice, presented as one card per option with
 * a short description of what tapping it does. Visually it follows the
 * survey-card pattern: neutral raised surface, magenta/violet fill for the
 * chosen one, and a quiet lift on hover.
 *
 * Rules from apps/web/AGENTS.md: solid fills only, no gradients, no blur;
 * depth from hairlines plus one soft shadow; press feedback is a transform;
 * animation never touches box-shadow; 3px focus ring on every card.
 */
import type { IntakeChoice } from "@/lib/business-intake";

const FOCUS =
  "focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet";

export default function IntakeChoiceGrid({
  choices,
  selected,
  onChoose,
  multiple = false,
  label,
  columns = "two",
}: {
  choices: IntakeChoice[];
  selected: string[];
  onChoose: (key: string) => void;
  multiple?: boolean;
  label: string;
  columns?: "two" | "three";
}) {
  return (
    <div
      role={multiple ? "group" : "radiogroup"}
      aria-label={label}
      className={`grid gap-2.5 ${columns === "three" ? "sm:grid-cols-2 xl:grid-cols-3" : "sm:grid-cols-2"}`}
    >
      {choices.map((choice) => {
        const active = selected.includes(choice.key);
        const notSure = choice.tone === "notSure";
        const surface = active
          ? notSure
            ? "border-amber-500 bg-amber-300 text-ink shadow-[0_10px_24px_-16px_rgba(120,53,15,0.9)]"
            : "border-deep-violet bg-deep-violet text-white shadow-[0_10px_24px_-16px_rgba(61,29,110,0.9)]"
          : notSure
            ? "border-amber-300 bg-amber-50 text-ink hover:border-amber-500 dark:bg-amber-950/20 dark:text-fog"
            : "border-ink/[0.08] bg-white text-ink hover:border-deep-violet/40 hover:bg-[#fbfaff] dark:border-white/10 dark:bg-[#241a45] dark:text-fog";

        return (
          <button
            key={choice.key}
            type="button"
            role={multiple ? undefined : "radio"}
            aria-checked={multiple ? undefined : active}
            aria-pressed={multiple ? active : undefined}
            onClick={() => onChoose(choice.key)}
            className={[
              "relative flex min-h-[104px] flex-col items-start justify-between gap-3 rounded-[8px] border p-4 text-start",
              "transition-[transform,border-color,background-color,color] duration-150 ease-out",
              "hover:-translate-y-[2px] active:translate-y-[2px] active:scale-[0.98]",
              FOCUS,
              surface,
            ].join(" ")}
          >
            <span className={`text-[13px] font-bold leading-snug ${choice.badge ? "pe-16" : ""}`}>
              {choice.title}
            </span>
            {choice.description ? (
              <span
                className={`text-[11px] leading-snug ${active ? (notSure ? "text-ink/60" : "text-white/75") : "text-ink/50 dark:text-fog/50"}`}
              >
                {choice.description}
              </span>
            ) : null}
            {choice.badge ? (
              <span
                className={`absolute end-3 top-3 rounded-full px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide ${
                  active ? "bg-white/20 text-white" : "bg-emerald-50 text-emerald-700"
                }`}
              >
                {choice.badge}
              </span>
            ) : null}
            {active ? (
              <span aria-hidden className="absolute bottom-3 end-3 text-[13px] font-bold">
                ✓
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
