import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import en from "@/lib/i18n/en";
import ar from "@/lib/i18n/ar";
import type { AiVisibilityGeneratedQuestion } from "@/lib/api-ai-visibility";
import QuestionResults from "./QuestionResults";

const question: AiVisibilityGeneratedQuestion = {
  id: "q1",
  query_set_id: "qs1",
  version: 1,
  question_key: "q001",
  question_text: "Is Sayvors licensed in Makkah?",
  language: "en",
  customer_intent: "licensing",
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
  recommended: false,
  incorrect: false,
};

describe("QuestionResults", () => {
  it("opens the brief for a researched question", () => {
    const onSelect = vi.fn();
    render(<QuestionResults questions={[question]} selectedRunId={null} onSelect={onSelect} copy={en.aiVisibility} />);
    fireEvent.click(screen.getByRole("button", { name: /Is Sayvors licensed/ }));
    expect(onSelect).toHaveBeenCalledWith("run1");
  });

  it("shows the branch label retained with an aggregated question", () => {
    const aggregatedQuestion = { ...question, channel_label: "Makkah Branch" };
    render(
      <QuestionResults
        questions={[aggregatedQuestion]}
        selectedRunId={null}
        onSelect={vi.fn()}
        copy={en.aiVisibility}
      />,
    );

    expect(screen.getByText("Makkah Branch")).toBeInTheDocument();
  });

  it("localizes English customer intent labels", () => {
    render(
      <QuestionResults
        questions={[{ ...question, customer_intent: "product_discovery" }]}
        selectedRunId={null}
        onSelect={vi.fn()}
        copy={en.aiVisibility}
      />,
    );

    expect(screen.getByText("Product discovery")).toBeInTheDocument();
    expect(screen.queryByText("product discovery")).not.toBeInTheDocument();
  });

  it("localizes Arabic customer intent and branch status labels", () => {
    render(
      <QuestionResults
        questions={[{ ...question, customer_intent: "licensing", status: "ambiguous" }]}
        selectedRunId={null}
        onSelect={vi.fn()}
        copy={ar.aiVisibility}
      />,
    );

    expect(screen.getByText("الترخيص")).toBeInTheDocument();
    expect(screen.queryByText("licensing")).not.toBeInTheDocument();
    expect(screen.getByText(ar.aiVisibility.stages.ambiguous)).toBeInTheDocument();
    expect(screen.queryByText("ambiguous")).not.toBeInTheDocument();
  });

  it("disables questions that have no run yet", () => {
    render(
      <QuestionResults
        questions={[{ ...question, status: "pending", run_id: null, mentioned: null, cited: null }]}
        selectedRunId={null}
        onSelect={vi.fn()}
        copy={en.aiVisibility}
      />,
    );
    expect(screen.getByRole("button", { name: /Is Sayvors licensed/ })).toBeDisabled();
  });
});
