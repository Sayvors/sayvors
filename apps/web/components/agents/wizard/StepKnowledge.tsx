import type { StepProps } from "@/lib/agent-wizard-data";
import { databanks } from "@/lib/agent-wizard-data";

export default function StepKnowledge({ data, update }: StepProps) {
  return (
    <div className="mx-auto max-w-xl space-y-8">
      <div className="text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-cyan-400 to-blue-500 text-white shadow-lg shadow-cyan-400/20">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <path d="M4 19V5a2 2 0 012-2h8l6 6v10a2 2 0 01-2 2H6a2 2 0 01-2-2z" />
            <path d="M14 3v6h6" />
            <path d="M8 13h8M8 17h4" />
          </svg>
        </div>
        <h2 className="mt-4 text-[18px] font-bold text-ink dark:text-fog">Connect a databank</h2>
        <p className="mt-1.5 text-[13px] text-ink/45 dark:text-fog/45">Choose where your agent gets its knowledge from. All your data is already in a databank.</p>
      </div>

      <div className="space-y-3">
        <div
          className={`relative cursor-pointer rounded-xl border-2 p-5 transition-all duration-150 ${
            data.databankId === ""
              ? "border-ink/[0.08] bg-fog/50 hover:border-ink/[0.15] dark:bg-ink/50 dark:hover:border-fog/[0.15]"
              : "border-ink/[0.08] bg-fog/50"
          }`}
          onClick={() => update("databankId", "")}
        >
          <div className="flex items-center gap-4">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-ink/[0.04] dark:bg-fog/[0.04]">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-6 w-6 text-ink/30 dark:text-fog/30">
                <circle cx="12" cy="12" r="10" />
                <path d="M12 8v8M8 12h8" strokeLinecap="round" />
              </svg>
            </div>
            <div>
              <span className={`text-[13px] font-semibold ${data.databankId === "" ? "text-deep-violet" : "text-ink dark:text-fog"}`}>No databank</span>
              <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">Agent will rely only on instructions</p>
            </div>
          </div>
          {data.databankId === "" && (
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="absolute right-4 top-4 h-4 w-4 text-deep-violet">
              <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>

        {databanks.map((db) => {
          const isSelected = data.databankId === db.id;
          return (
            <div
              key={db.id}
              className={`relative cursor-pointer rounded-xl border-2 p-5 transition-all duration-150 ${
                isSelected
                  ? "border-deep-violet bg-deep-violet/[0.04] shadow-sm shadow-deep-violet/10"
                  : "border-transparent bg-fog/50 hover:border-ink/[0.08] hover:bg-fog dark:bg-ink/50 dark:hover:border-fog/[0.08]"
              }`}
              onClick={() => update("databankId", db.id)}
            >
              <div className="flex items-center gap-4">
                <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${isSelected ? "bg-deep-violet/10" : "bg-ink/[0.04] dark:bg-fog/[0.04]"}`}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className={`h-6 w-6 ${isSelected ? "text-deep-violet" : "text-ink/30 dark:text-fog/30"}`}>
                    <path d="M4 19V5a2 2 0 012-2h8l6 6v10a2 2 0 01-2 2H6a2 2 0 01-2-2z" strokeLinecap="round" strokeLinejoin="round" />
                    <path d="M14 3v6h6" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <div>
                  <span className={`text-[13px] font-semibold ${isSelected ? "text-deep-violet" : "text-ink dark:text-fog"}`}>{db.name}</span>
                  <p className="mt-0.5 text-[11px] text-ink/40 dark:text-fog/40">{db.docs} documents</p>
                </div>
              </div>
              {isSelected && (
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="absolute right-4 top-4 h-4 w-4 text-deep-violet">
                  <path d="M3 8.5l3.5 3.5 6.5-7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
