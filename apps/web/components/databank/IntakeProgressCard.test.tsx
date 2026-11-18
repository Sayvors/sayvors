import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { apiFetch } from "@/lib/api-rag";
import type { IntakeQuestion, IntakeResponse } from "@/lib/business-intake";
import IntakeProgressCard from "./IntakeProgressCard";

vi.mock("@/lib/api-rag", () => ({ apiFetch: vi.fn() }));

const q = (over: Partial<IntakeQuestion> = {}): IntakeQuestion => ({
  key: "dietary",
  label: "Dietary options",
  source: "ask",
  options: ["Halal", "Vegan"],
  multiple: true,
  fact_key: "dietary",
  section: "offering",
  section_label: "What you offer",
  answer: [],
  skipped: false,
  answer_source: "manual",
  google_value: null,
  ...over,
});

const response = (over: Partial<IntakeResponse> = {}): IntakeResponse => ({
  vertical_key: "restaurant",
  vertical_label: "Food & Restaurant",
  sub_focus: "dine_in",
  sub_focuses: [],
  verticals: [],
  questions: [
    q({ key: "dietary", answer: ["Halal"], answer_source: "google_confirmed" }),
    q({ key: "signature", label: "Signature dishes" }),
    q({
      key: "price_range",
      label: "Typical price",
      section: "payments",
      section_label: "Payments & pricing",
      options: ["Under 50", "50–100"],
      skipped: true,
    }),
    q({
      key: "payments",
      label: "How can customers pay?",
      section: "payments",
      section_label: "Payments & pricing",
      options: ["Cash", "Credit card"],
    }),
    q({
      key: "parking",
      label: "Parking",
      section: "access",
      section_label: "Access & facilities",
      options: ["Free parking"],
    }),
    q({
      key: "languages_spoken",
      label: "Languages your team speaks",
      section: "access",
      section_label: "Access & facilities",
      options: ["English", "Arabic"],
    }),
  ],
  sections: [
    { key: "offering", label: "What you offer", answered: 1, total: 2, remaining: 1 },
    { key: "payments", label: "Payments & pricing", answered: 0, total: 2, remaining: 2 },
    { key: "access", label: "Access & facilities", answered: 0, total: 2, remaining: 2 },
  ],
  answered: 1,
  skipped: 1,
  total: 6,
  google_suggestion: null,
  ...over,
});

beforeEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("intake progress card", () => {
  it("shows the next three unanswered questions and deep-links each one", async () => {
    vi.mocked(apiFetch).mockResolvedValue(response());
    render(<IntakeProgressCard />);

    expect(await screen.findByText("5 questions left to answer", {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText("1 of 6 answered")).toBeInTheDocument();
    expect(screen.getByText("1 skipped")).toBeInTheDocument();

    const checklist = within(screen.getByRole("list")).getAllByRole("link");
    expect(checklist).toHaveLength(3);
    expect(checklist.map((link) => link.getAttribute("href"))).toEqual([
      "/dashboard/business-intake?focus=offering&q=signature",
      "/dashboard/business-intake?focus=payments&q=price_range",
      "/dashboard/business-intake?focus=payments&q=payments",
    ]);
    expect(within(screen.getByRole("list")).getByText("Skipped")).toBeInTheDocument();
    expect(screen.getByText("2 more after these")).toBeInTheDocument();

    const cta = screen.getByRole("link", { name: /answer 3 more/i });
    expect(cta).toHaveAttribute(
      "href",
      "/dashboard/business-intake?focus=offering&q=signature",
    );
  });

  it("groups saved answers by section and gives every row its own Change link", async () => {
    vi.mocked(apiFetch).mockResolvedValue(response());
    const user = userEvent.setup();
    render(<IntakeProgressCard />);
    await screen.findByText("5 questions left to answer", {}, { timeout: 5000 });

    const toggle = screen.getByRole("button", { name: /view my answers/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");

    const table = screen.getByRole("table");
    expect(within(table).getByText("What you offer")).toBeInTheDocument();
    expect(within(table).getByText("Payments & pricing")).toBeInTheDocument();
    expect(within(table).getByText("Access & facilities")).toBeInTheDocument();
    expect(within(table).getByText("1 of 2")).toBeInTheDocument();

    expect(within(table).getByText("Halal")).toBeInTheDocument();
    expect(within(table).getByText("From Google")).toBeInTheDocument();

    const changes = within(table).getAllByRole("link", { name: "Change" });
    expect(changes).toHaveLength(6);
    expect(changes[0]).toHaveAttribute(
      "href",
      "/dashboard/business-intake?focus=offering&q=dietary",
    );
    expect(changes[2]).toHaveAttribute(
      "href",
      "/dashboard/business-intake?focus=payments&q=price_range",
    );
  });

  it("switches to an edit-only card once every question is answered", async () => {
    vi.mocked(apiFetch).mockResolvedValue(
      response({
        questions: [
          q({ key: "dietary", answer: ["Halal"] }),
          q({ key: "signature", label: "Signature dishes", answer: ["Shawarma"] }),
        ],
        sections: [
          { key: "offering", label: "What you offer", answered: 2, total: 2, remaining: 0 },
        ],
        answered: 2,
        skipped: 0,
        total: 2,
      }),
    );
    render(<IntakeProgressCard />);

    expect(await screen.findByText(/all caught up/i, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.queryByText("Still to answer")).toBeNull();
    const cta = screen.getByRole("link", { name: /edit answers/i });
    expect(cta).toHaveAttribute("href", "/dashboard/business-intake");
  });

  it("still offers the questionnaire when progress cannot be loaded", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("offline"));
    render(<IntakeProgressCard />);

    const cta = await screen.findByRole("link", { name: /answer questions/i }, { timeout: 5000 });
    expect(cta).toHaveAttribute("href", "/dashboard/business-intake");
  });
});
