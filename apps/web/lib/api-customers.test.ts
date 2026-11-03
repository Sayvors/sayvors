import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchCustomers } from "./api-customers";

function mockFetch(payload: unknown) {
  const urls: string[] = [];
  const fetchMock = vi.fn(async (url: RequestInfo | URL) => {
    urls.push(String(url));
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return urls;
}

describe("fetchCustomers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("forwards SQL filters, sort and cursor, and returns the page contract", async () => {
    const urls = mockFetch({
      customers: [{ channel_id: "chan-1", key: "966500000001" }],
      total: 42,
      next_cursor: "next-page",
    });

    const page = await fetchCustomers({
      search: "ahmed",
      platform: "whatsapp",
      category: "complaint",
      priority: "high",
      important: true,
      limit: 200,
      sort: "important",
      cursor: "page-2",
    });

    expect(page.customers).toHaveLength(1);
    expect(page.total).toBe(42);
    expect(page.next_cursor).toBe("next-page");
    const url = urls[0];
    expect(url).toContain("search=ahmed");
    expect(url).toContain("platform=whatsapp");
    expect(url).toContain("category=complaint");
    expect(url).toContain("priority=high");
    expect(url).toContain("important=true");
    expect(url).toContain("limit=200");
    expect(url).toContain("sort=important");
    expect(url).toContain("cursor=page-2");
  });

  it("omits the all-platforms/all-categories sentinels", async () => {
    const urls = mockFetch({ customers: [], total: 0, next_cursor: null });

    await fetchCustomers({ platform: "all", category: "all", priority: "all" });

    expect(urls[0]).not.toContain("platform=");
    expect(urls[0]).not.toContain("category=");
    expect(urls[0]).not.toContain("priority=");
  });
});
