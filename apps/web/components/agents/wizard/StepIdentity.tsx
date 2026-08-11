import type { StepProps } from "@/lib/agent-wizard-data";
import { personaList, personaInstructions } from "@/lib/agent-wizard-data";

export default function StepIdentity({ data, update }: StepProps) {
  return (
    <div className="mx-auto max-w-xl space-y-8">
      <div className="text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet to-magenta text-white shadow-lg shadow-deep-violet/20">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <rect x="3" y="11" width="18" height="10" rx="2" />
            <circle cx="12" cy="5" r="2" />
            <path d="M12 7v4M8 11v4M16 11v4" />
          </svg>
        </div>
        <h2 className="mt-4 text-[18px] font-bold text-ink dark:text-fog">What should we call this agent?</h2>
        <p className="mt-1.5 text-[13px] text-ink/45 dark:text-fog/45">Give it a name and pick a role. You can always change these later.</p>
      </div>

      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-[12px] font-semibold text-ink/70 dark:text-fog/70 mb-1.5">Agent Name</label>
            <input
              type="text"
              value={data.name}
              onChange={(e) => update("name", e.target.value)}
              placeholder="e.g. Support Bot"
              className="w-full rounded-xl border border-ink/[0.08] bg-fog/50 px-4 py-3 text-[14px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.08] dark:border-fog/[0.08] dark:bg-ink/50 dark:text-fog dark:placeholder:text-fog/25 dark:focus:bg-ink"
            />
          </div>
          <div>
            <label className="block text-[12px] font-semibold text-ink/70 dark:text-fog/70 mb-1.5">Description</label>
            <input
              type="text"
              value={data.description}
              onChange={(e) => update("description", e.target.value)}
              placeholder="One line about what it does"
              className="w-full rounded-xl border border-ink/[0.08] bg-fog/50 px-4 py-3 text-[14px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.08] dark:border-fog/[0.08] dark:bg-ink/50 dark:text-fog dark:placeholder:text-fog/25 dark:focus:bg-ink"
            />
          </div>
        </div>
      </div>

      <div>
        <div className="mb-3">
          <label className="block text-[12px] font-semibold text-ink/70 dark:text-fog/70">What role does it play?</label>
          <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">This sets the default personality and behavior for your agent.</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {personaList.map((p) => {
            const isSelected = data.persona === p.id;
            return (
              <button
                key={p.id}
                onClick={() => {
                  update("persona", p.id);
                  if (p.id !== "Custom" && personaInstructions[p.id]) {
                    update("coreInstructions", personaInstructions[p.id]);
                  }
                }}
                className={`group flex items-start gap-3.5 rounded-xl border-2 p-4 text-left transition-all duration-150 ${
                  isSelected
                    ? "border-deep-violet bg-deep-violet/[0.04] shadow-sm shadow-deep-violet/10"
                    : "border-transparent bg-fog/50 hover:border-ink/[0.08] hover:bg-fog dark:bg-ink/50 dark:hover:border-fog/[0.08]"
                }`}
              >
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-[20px] transition ${
                  isSelected ? "bg-deep-violet/10" : "bg-ink/[0.04] group-hover:bg-ink/[0.06] dark:bg-fog/[0.04]"
                }`}>
                  {p.icon}
                </span>
                <div className="min-w-0">
                  <span className={`text-[13px] font-semibold ${isSelected ? "text-deep-violet" : "text-ink dark:text-fog"}`}>{p.id}</span>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-ink/40 dark:text-fog/40">{p.desc}</p>
                </div>
                {isSelected && (
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="ml-auto mt-0.5 h-4 w-4 shrink-0 text-deep-violet">
                    <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
