const MESSAGES: Record<string, string> = {
  retry_limit_reached:
    "Research is busy for this question. A slot opens within an hour and your question is saved.",
  retry_cooldown:
    "Research is cooling down for this question. Try again in about a minute.",
  tenant_search_rate_limited:
    "This workspace reached its research limit. Wait a minute and try again.",
  search_blocked:
    "Public web search is paused right now. Your question is saved, so try again shortly.",
  search_unavailable:
    "Public web search is unavailable right now. Your question is saved, so try again shortly.",
  invalid_research_json:
    "The research model returned a brief we could not verify. Please retry.",
  no_llm_model_configured:
    "No AI model is connected. Ask a workspace admin to configure one.",
  budget_exhausted:
    "AI credit is exhausted. Top up credit, then run this question again.",
};

/** Turn a backend policy code into a sentence an owner can act on. */
export function researchErrorMessage(raw: string | null | undefined): string {
  if (!raw) return "Research could not finish. Your question is saved.";
  const code = raw.trim();
  return (
    MESSAGES[code] ??
    (code.length <= 64 && /^[a-z0-9_]+$/.test(code)
      ? "Research could not finish. Your question is saved. Try again."
      : code)
  );
}
