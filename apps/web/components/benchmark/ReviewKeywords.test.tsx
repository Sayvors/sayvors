import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import ReviewKeywords from "./ReviewKeywords";
import { useI18n } from "@/lib/i18n/I18nProvider";
import en from "@/lib/i18n/en";
import ar from "@/lib/i18n/ar";
import type {
  ReviewThemeCell,
  ReviewThemeQuote,
  ReviewThemesResponse,
} from "@/lib/api-benchmark";

vi.mock("@/lib/i18n/I18nProvider", async () => {
  const actual = await vi.importActual<typeof import("@/lib/i18n/I18nProvider")>(
    "@/lib/i18n/I18nProvider",
  );
  return { ...actual, useI18n: vi.fn(actual.useI18n) };
});

const quote: ReviewThemeQuote = {
  review_id: "r1",
  quote: "staff were kind",
  review_text: "The staff were kind and quick.",
  rating: 5,
  author: "Sara A",
  author_photo: null,
  reviewed_at: "2026-11-01T12:00:00Z",
  review_url: "https://www.google.com/maps/review/r1",
};

function cell(mentions: number, sampleSize: number, quotes: ReviewThemeQuote[] = []): ReviewThemeCell {
  return {
    mentions,
    sample_size: sampleSize,
    percentage: sampleSize ? (mentions / sampleSize) * 100 : 0,
    positive: mentions,
    negative: 0,
    quotes,
  };
}

const readyData: ReviewThemesResponse = {
  subjects: [
    { key: "own:mine", name: "My Branch", kind: "own", status: "ready", sample_size: 10, sample_hash: "a", analyzed_at: null },
    { key: "saved:peer1", name: "Peer One", kind: "saved", status: "ready", sample_size: 20, sample_hash: "b", analyzed_at: null },
    { key: "saved:peer2", name: "Peer Two", kind: "saved", status: "ready", sample_size: 20, sample_hash: "c", analyzed_at: null },
  ],
  rows: [
    {
      key: "friendly", label: "Friendly service", sentiment: "positive",
      cells: { "own:mine": cell(2, 10, [quote]), "saved:peer1": cell(4, 20), "saved:peer2": cell(10, 20) },
    },
    {
      key: "wait", label: "Long wait", sentiment: "negative",
      cells: { "own:mine": cell(1, 10), "saved:peer1": cell(2, 20), "saved:peer2": cell(3, 20) },
    },
    {
      key: "value", label: "Good value", sentiment: "mixed",
      cells: { "own:mine": cell(1, 10), "saved:peer1": cell(2, 20), "saved:peer2": cell(2, 20) },
    },
  ],
};

function renderKeywords(overrides: Partial<React.ComponentProps<typeof ReviewKeywords>> = {}) {
  return render(
    <ReviewKeywords
      data={readyData}
      mainKey="own:mine"
      loading={false}
      fetching={false}
      error={null}
      onRetry={vi.fn()}
      {...overrides}
    />,
  );
}

beforeEach(() => {
  vi.mocked(useI18n).mockReturnValue({ locale: "en", dir: "ltr", t: en, setLocale: vi.fn() });
});

describe("ReviewKeywords grid", () => {
  it("renders sampled counts, percentages, sentiment, bars and computed peer comparison", () => {
    renderKeywords();

    expect(screen.getByRole("heading", { name: "Review keywords" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Review keywords" })).toBeInTheDocument();
    expect(screen.getByText("2 of 10 reviews analyzed (20%)")).toBeInTheDocument();
    expect(screen.getAllByText("Positive").length).toBeGreaterThan(0);
    expect(screen.getByText("Peer median: 35%")).toBeInTheDocument();
    expect(screen.getByText("Selected: 15 pts below peer median")).toBeInTheDocument();
    expect(screen.getByText("10 reviews analyzed")).toBeInTheDocument();
    expect(screen.getByLabelText("Friendly service mention share for My Branch").style.width).toBe("20%");
  });

  it("uses each cell's own sentiment instead of the row-wide sentiment", () => {
    const negativePeer = { ...cell(4, 20), positive: 0, negative: 4 };
    renderKeywords({
      data: {
        subjects: readyData.subjects,
        rows: [{
          ...readyData.rows[0],
          cells: { ...readyData.rows[0].cells, "saved:peer1": negativePeer },
        }],
      },
    });

    const count = screen.getByText("4 of 20 reviews analyzed (20%)");
    expect(within(count.closest("td")!).getByText("Negative")).toBeInTheDocument();
  });

  it("filters positive and negative themes while keeping mixed themes only under All", () => {
    renderKeywords();

    fireEvent.click(screen.getByRole("button", { name: "Positive" }));
    expect(screen.getByText("Friendly service")).toBeInTheDocument();
    expect(screen.queryByText("Long wait")).not.toBeInTheDocument();
    expect(screen.queryByText("Good value")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Positive" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Negative" }));
    expect(screen.getByText("Long wait")).toBeInTheDocument();
    expect(screen.queryByText("Friendly service")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Good value")).toBeInTheDocument();
  });

  it("prefers server-supplied peer median and own gap when present", () => {
    const row = {
      ...readyData.rows[0],
      peer_median_pct: 42,
      own_pct: 20,
      gap_pct: -22,
    };
    renderKeywords({ data: { subjects: readyData.subjects, rows: [row] } });

    expect(screen.getByText("Peer median: 42%")).toBeInTheDocument();
    expect(screen.getByText("Selected: 22 pts below peer median")).toBeInTheDocument();
  });

  it("marks a saved main selection as Selected business rather than Your branch", () => {
    renderKeywords({ mainKey: "saved:peer1" });

    expect(screen.getByRole("columnheader", { name: /Peer One.*Selected business/ })).toBeInTheDocument();
    expect(screen.queryByText("Your branch")).not.toBeInTheDocument();
  });

  it("offers a mobile business selector that selects one table column", () => {
    renderKeywords();

    const selector = screen.getByLabelText("Business");
    expect(within(selector).getAllByRole("option")).toHaveLength(3);
    fireEvent.change(selector, { target: { value: "saved:peer2" } });

    expect(screen.getByRole("columnheader", { name: /Peer Two/ })).toHaveAttribute("data-mobile-selected", "true");
    expect(screen.getByRole("columnheader", { name: /My Branch/ })).toHaveAttribute("data-mobile-selected", "false");
  });

  it("renders a missing ready cell as zero mentions rather than unavailable", () => {
    renderKeywords({
      data: {
        subjects: [readyData.subjects[0], readyData.subjects[1]],
        rows: [{ key: "peer-only", label: "Peer only theme", sentiment: "positive", cells: { "saved:peer1": cell(1, 20) } }],
      },
    });

    expect(screen.getByText("0 of 10 reviews analyzed (0%)")).toBeInTheDocument();
    expect(screen.queryByText("No cached sample")).not.toBeInTheDocument();
  });

  it("shows a filter-specific empty state when no theme matches", () => {
    renderKeywords({
      data: { subjects: readyData.subjects, rows: [readyData.rows[0]] },
    });

    fireEvent.click(screen.getByRole("button", { name: "Negative" }));
    expect(screen.getByText("No negative themes in this sample.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("labels samples below five reviews as low sample", () => {
    renderKeywords({
      data: {
        subjects: [{ key: "own:mine", name: "My Branch", kind: "own", status: "ready", sample_size: 4, sample_hash: "a", analyzed_at: null }],
        rows: [{ key: "kind", label: "Kind staff", sentiment: "positive", cells: { "own:mine": cell(1, 4) } }],
      },
    });

    expect(screen.getByText("Low sample")).toBeInTheDocument();
    expect(screen.getByText("4 reviews analyzed")).toBeInTheDocument();
  });
});

describe("ReviewKeywords states", () => {
  it("shows a loader on the initial request", () => {
    renderKeywords({ data: undefined, loading: true });

    expect(screen.getByRole("status", { name: "Loading review themes…" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("distinguishes ready zero themes from an unavailable cached sample", () => {
    const { rerender } = renderKeywords({
      data: { subjects: [readyData.subjects[0]], rows: [] },
    });
    expect(screen.getByText("No repeated themes in this sample.")).toBeInTheDocument();
    expect(screen.queryByText("No cached sample")).not.toBeInTheDocument();

    rerender(
      <ReviewKeywords
        data={{
          subjects: [{ ...readyData.subjects[0], status: "unavailable", sample_size: 0 }],
          rows: [],
        }}
        mainKey="own:mine"
        loading={false}
        fetching={false}
        error={null}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByText("No cached sample")).toBeInTheDocument();
    expect(screen.queryByText("No repeated themes in this sample.")).not.toBeInTheDocument();
  });

  it("does not claim a finished empty result while another sample is pending", () => {
    renderKeywords({
      data: {
        subjects: [readyData.subjects[0], { ...readyData.subjects[1], status: "pending" }],
        rows: [],
      },
    });

    expect(screen.getByText("Themes will appear as each review sample finishes analysis.")).toBeInTheDocument();
    expect(screen.queryByText("No repeated themes in this sample.")).not.toBeInTheDocument();
    expect(screen.getByText("Analyzing…")).toBeInTheDocument();
  });

  it("keeps ready zero themes visible alongside an unavailable peer", () => {
    renderKeywords({
      data: {
        subjects: [readyData.subjects[0], { ...readyData.subjects[1], status: "unavailable" }],
        rows: [],
      },
    });

    expect(screen.getByText("No repeated themes in this sample.")).toBeInTheDocument();
    expect(screen.getByText("No cached sample")).toBeInTheDocument();
  });

  it("keeps ready rows visible while a peer is pending", () => {
    renderKeywords({
      data: {
        subjects: [readyData.subjects[0], { ...readyData.subjects[1], status: "pending" }],
        rows: [readyData.rows[0]],
      },
    });

    expect(screen.getByText(/Analyzing review themes for 1 business/)).toBeInTheDocument();
    expect(screen.getAllByText("Analyzing…").length).toBeGreaterThan(0);
    expect(screen.getByText("2 of 10 reviews analyzed (20%)")).toBeInTheDocument();
  });

  it("shows per-subject errors with retry instead of inventing zero mentions", () => {
    const onRetry = vi.fn();
    renderKeywords({
      data: {
        subjects: [readyData.subjects[0], { ...readyData.subjects[1], status: "error" }],
        rows: [readyData.rows[0]],
      },
      onRetry,
    });

    expect(screen.getByText("Theme analysis failed.")).toBeInTheDocument();
    expect(screen.queryByText("0 of 0 reviews analyzed (0%)")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry Peer One" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows a whole-request error alert with retry", () => {
    const onRetry = vi.fn();
    renderKeywords({ data: undefined, error: new Error("offline"), onRetry });

    expect(screen.getByRole("alert")).toHaveTextContent("Could not load review themes.");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("keeps cached data while a background refresh is running", () => {
    renderKeywords({ fetching: true });

    expect(screen.getByText("Refreshing…")).toBeInTheDocument();
    expect(screen.getByText("Friendly service")).toBeInTheDocument();
  });
});

describe("ReviewKeywords quote dialog", () => {
  it("opens an accessible native quote button and restores focus after close", async () => {
    renderKeywords();
    const trigger = screen.getByRole("button", {
      name: "Friendly service, My Branch: 2 of 10 reviews analyzed (20%). Open quotes.",
    });

    trigger.focus();
    fireEvent.click(trigger);
    const dialog = screen.getByRole("dialog", { name: "Friendly service — review quotes" });
    expect(dialog).toHaveTextContent("My Branch · 2 of 10 reviews analyzed (20%)");
    expect(within(dialog).getByText("Sara A")).toBeInTheDocument();
    expect(within(dialog).getByText("5★")).toBeInTheDocument();
    expect(within(dialog).getByText(/2026/)).toBeInTheDocument();
    expect(within(dialog).getByText("staff were kind").tagName).toBe("MARK");
    expect(within(dialog).getByRole("link", { name: "View on Google" })).toHaveAttribute("href", quote.review_url);
    expect(within(dialog).getByRole("button", { name: "Close" })).toHaveFocus();

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("traps focus and closes on Escape", () => {
    renderKeywords();
    const trigger = screen.getByRole("button", { name: /Friendly service, My Branch/ });
    trigger.focus();
    fireEvent.click(trigger);

    const close = screen.getByRole("button", { name: "Close" });
    const sourceLink = screen.getByRole("link", { name: "View on Google" });
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(sourceLink).toHaveFocus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(close).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("bounds quote cards and reports when more evidence exists", () => {
    const quotes = Array.from({ length: 8 }, (_, index) => ({
      ...quote,
      review_id: `r${index}`,
      quote: `staff were kind ${index}`,
      review_text: `The staff were kind ${index}.`,
    }));
    renderKeywords({
      data: {
        subjects: [readyData.subjects[0]],
        rows: [{ key: "kind", label: "Kind staff", sentiment: "positive", cells: { "own:mine": cell(8, 10, quotes) } }],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: /Kind staff, My Branch/ }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getAllByRole("article")).toHaveLength(6);
    expect(within(dialog).getByText("Showing 6 of 8 quotes")).toBeInTheDocument();
  });

  it("uses Arabic copy, dir=auto review text and a localized close label", () => {
    vi.mocked(useI18n).mockReturnValue({ locale: "ar", dir: "rtl", t: ar, setLocale: vi.fn() });
    renderKeywords({
      data: {
        subjects: [{ ...readyData.subjects[0], name: "فرعي" }],
        rows: [{
          key: "kind", label: "خدمة ممتازة", sentiment: "positive",
          cells: { "own:mine": cell(1, 10, [{ ...quote, quote: "فريق لطيف", review_text: "كان الفريق لطيفاً جداً." }]) },
        }],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: /خدمة ممتازة، فرعي/ }));
    expect(screen.getByRole("button", { name: "إغلاق" })).toHaveFocus();
    expect(screen.getByText("فريق لطيف").closest("p")).toHaveAttribute("dir", "auto");
    expect(screen.getByText("فريق لطيف").tagName).toBe("MARK");
  });

  it("does not render an unsafe review URL", () => {
    renderKeywords({
      data: {
        subjects: [readyData.subjects[0]],
        rows: [{
          key: "kind", label: "Kind staff", sentiment: "positive",
          cells: { "own:mine": cell(1, 10, [{ ...quote, review_url: "javascript:alert(1)" }]) },
        }],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: /Kind staff, My Branch/ }));
    expect(screen.queryByRole("link", { name: "View on Google" })).not.toBeInTheDocument();
  });
});
