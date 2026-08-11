import type { StepProps } from "@/lib/agent-wizard-data";

export default function StepInstructions({ data, update }: StepProps) {
  return (
    <div className="mx-auto max-w-xl space-y-8">
      <div className="text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-400 to-orange-500 text-white shadow-lg shadow-amber-400/20">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
            <path d="M12 2l1.5 5.5L19 9l-5.5 1.5L12 16l-1.5-5.5L5 9l5.5-1.5L12 2z" />
          </svg>
        </div>
        <h2 className="mt-4 text-[18px] font-bold text-ink dark:text-fog">How should it behave?</h2>
        <p className="mt-1.5 text-[13px] text-ink/45 dark:text-fog/45">Write instructions that define the agent&apos;s personality and rules.</p>
      </div>

      <div className="space-y-5">
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="text-[12px] font-semibold text-ink/70 dark:text-fog/70">Core Instructions</label>
            <button className="flex items-center gap-1 text-[11px] font-medium text-deep-violet transition hover:text-deep-violet/80">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
                <path d="M8 2l1.5 4.5L14 8l-4.5 1.5L8 14l-1.5-4.5L2 8l4.5-1.5L8 2z" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Enhance with AI
            </button>
          </div>
          <textarea
            value={data.coreInstructions}
            onChange={(e) => update("coreInstructions", e.target.value)}
            rows={7}
            placeholder="You are a helpful agent. Be friendly, concise, and always try to solve the user's problem..."
            className="w-full rounded-xl border border-ink/[0.08] bg-fog/50 px-4 py-3 text-[13px] leading-relaxed text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/40 focus:bg-white focus:ring-2 focus:ring-deep-violet/[0.08] dark:border-fog/[0.08] dark:bg-ink/50 dark:text-fog dark:placeholder:text-fog/25 dark:focus:bg-ink"
          />
          <div className="mt-1.5 flex items-center justify-between">
            <p className="text-[10px] text-ink/30 dark:text-fog/30">{data.coreInstructions.length} characters</p>
            <p className="text-[10px] text-ink/30 dark:text-fog/30">Tip: Be specific about tone, rules, and escalation.</p>
          </div>
        </div>

        <div className="rounded-xl border border-ink/[0.06] bg-fog/30 p-4 dark:bg-ink/30">
          <label className="block text-[12px] font-semibold text-ink/70 dark:text-fog/70 mb-3">
            Creativity: {data.creativity}%
            <span className="ml-2 text-ink/30 dark:text-fog/30 font-normal">
              {data.creativity <= 20 ? "Precise" : data.creativity <= 40 ? "Balanced" : data.creativity <= 60 ? "Moderate" : data.creativity <= 80 ? "Creative" : "Very Creative"}
            </span>
          </label>
          <input
            type="range"
            min={0}
            max={100}
            value={data.creativity}
            onChange={(e) => update("creativity", Number(e.target.value))}
            className="w-full accent-deep-violet"
          />
          <div className="mt-1 flex justify-between text-[9px] text-ink/25 dark:text-fog/25">
            <span>Sticks to facts</span>
            <span>Wild imagination</span>
          </div>
        </div>

        <div>
          <label className="block text-[12px] font-semibold text-ink/70 dark:text-fog/70 mb-2">Training Mode</label>
          <div className="flex gap-0.5 rounded-xl bg-fog/50 p-1 dark:bg-ink/50 w-fit">
            <button
              onClick={() => update("trainingMode", "zero-shot")}
              className={`rounded-lg px-5 py-2.5 text-[12px] font-semibold transition-all duration-150 ${
                data.trainingMode === "zero-shot"
                  ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet"
                  : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
              }`}
            >
              Zero-shot
            </button>
            <button
              onClick={() => update("trainingMode", "few-shot")}
              className={`rounded-lg px-5 py-2.5 text-[12px] font-semibold transition-all duration-150 ${
                data.trainingMode === "few-shot"
                  ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-deep-violet"
                  : "text-ink/40 hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60"
              }`}
            >
              Few-shot
            </button>
          </div>
          <p className="mt-2 text-[11px] text-ink/40 dark:text-fog/40">
            {data.trainingMode === "zero-shot"
              ? "The agent follows your instructions alone. No examples needed."
              : "Provide example conversations so the agent learns exact patterns."}
          </p>
        </div>

        {data.trainingMode === "few-shot" && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[12px] font-medium text-ink/50 dark:text-fog/50">{data.examples.length} examples</span>
              <button
                onClick={() => update("examples", [...data.examples, { message: "", reply: "", tag: "" }])}
                className="flex items-center gap-1 rounded-lg bg-deep-violet px-3 py-1.5 text-[11px] font-semibold text-white transition hover:bg-deep-violet/90"
              >
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3">
                  <path d="M8 3v10M3 8h10" strokeLinecap="round" />
                </svg>
                Add example
              </button>
            </div>

            {data.examples.length === 0 ? (
              <div className="rounded-xl border border-dashed border-ink/[0.1] p-8 text-center dark:border-fog/[0.1]">
                <p className="text-[13px] text-ink/40 dark:text-fog/40">No examples yet. Add Q&A pairs to train the agent.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {data.examples.map((ex, i) => (
                  <div key={i} className="rounded-xl border border-ink/[0.06] bg-fog/30 p-3 dark:bg-ink/30 dark:border-fog/[0.06]">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-ink/30 dark:text-fog/30">Example {i + 1}</span>
                      <button
                        onClick={() => update("examples", data.examples.filter((_, j) => j !== i))}
                        className="rounded p-1 text-ink/25 transition hover:bg-coral/10 hover:text-coral dark:text-fog/25"
                      >
                        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3">
                          <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
                        </svg>
                      </button>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-3">
                      <input
                        type="text"
                        value={ex.message}
                        onChange={(e) => {
                          const updated = data.examples.map((x, j) => (j === i ? { ...x, message: e.target.value } : x));
                          update("examples", updated);
                        }}
                        placeholder="Customer says..."
                        className="rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[11px] text-ink outline-none placeholder:text-ink/25 focus:border-deep-violet/30 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                      />
                      <input
                        type="text"
                        value={ex.reply}
                        onChange={(e) => {
                          const updated = data.examples.map((x, j) => (j === i ? { ...x, reply: e.target.value } : x));
                          update("examples", updated);
                        }}
                        placeholder="Agent replies..."
                        className="rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[11px] text-ink outline-none placeholder:text-ink/25 focus:border-deep-violet/30 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                      />
                      <input
                        type="text"
                        value={ex.tag}
                        onChange={(e) => {
                          const updated = data.examples.map((x, j) => (j === i ? { ...x, tag: e.target.value } : x));
                          update("examples", updated);
                        }}
                        placeholder="Tag (optional)"
                        className="rounded-lg border border-ink/[0.06] bg-white px-3 py-2 text-[11px] text-ink outline-none placeholder:text-ink/25 focus:border-deep-violet/30 dark:border-fog/[0.06] dark:bg-ink dark:text-fog dark:placeholder:text-fog/25"
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
