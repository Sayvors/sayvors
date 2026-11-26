import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import en from "@/lib/i18n/en";
import type { AiVisibilityGeneratedQuestion } from "@/lib/api-ai-visibility";
import IntentCoverageChart from "./IntentCoverageChart";

const base: AiVisibilityGeneratedQuestion = {
  id: "q1",
  query_set_id: "qs1",
  version: 1,
  question_key: "q001",
  question_text: "Question",
  language: "en",
  customer_intent: "recommendation",
  industry_relevance: 90,
  service_relevance: 95,
  geographic_context: "Makkah",
  business_relevance_score: 92,
  research_priority: "P1",
  origin: "initial",
  status: "completed",
  run_id: "run1",
  mentioned: true,
  cited: true,
  recommended: true,
  incorrect: false,
};

describe("IntentCoverageChart", () => {
  it("groups questions by customer intent", () => {
    render(
      <IntentCoverageChart
        questions={[base, { ...base, id: "q2", question_key: "q002", status: "pending", run_id: null }]}
        copy={en.aiVisibility}
      />,
    );
    expect(screen.getByLabelText("Customer intent coverage")).toBeInTheDocument();
    expect(screen.getByText("Recommendation")).toBeInTheDocument();
    expect(screen.getByText("1/2")).toBeInTheDocument();
  });
});
