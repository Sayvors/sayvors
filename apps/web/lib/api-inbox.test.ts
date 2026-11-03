import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchInboxThreads, fetchThreadMessages, INBOX_THREAD_PAGE_SIZE } from "./api-inbox";

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

describe("fetchThreadMessages", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("opens with the capped window and no cursor", async () => {
    const urls = mockFetch({
      messages: [],
      thread: null,
      next_cursor: null,
    });

    const data = await fetchThreadMessages("chan-1", "+966500000001");

    expect(data).toEqual({ messages: [], thread: null, next_cursor: null });
    const url = urls[0];
    expect(url).toContain("/api/v1/inbox/threads/chan-1/%2B966500000001");
    expect(url).toContain(`limit=${INBOX_THREAD_PAGE_SIZE}`);
    expect(url).not.toContain("before=");
  });

  it("passes the older-page cursor and custom limit", async () => {
    const urls = mockFetch({
      messages: [],
      thread: null,
      next_cursor: null,
    });

    await fetchThreadMessages("chan-1", null, {
      before: "m-2",
      limit: 50,
    });

    const url = urls[0];
    expect(url).toContain("/api/v1/inbox/threads/chan-1/unknown");
    expect(url).toContain("limit=50");
    expect(url).toContain("before=m-2");
  });

  it("surfaces next_cursor from the response", async () => {
    mockFetch({
      messages: [{ id: "m-3", content: "newest" }],
      thread: null,
      next_cursor: "m-3",
    });

    const data = await fetchThreadMessages("chan-1", "+966500000001");

    expect(data.next_cursor).toBe("m-3");
  });
});

describe("fetchInboxThreads", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the page contract and forwards cursor/filters", async () => {
    const urls = mockFetch({
      threads: [{ channel_id: "chan-1", key: "966500000001" }],
      total: 42,
      next_cursor: "next-page",
    });

    const page = await fetchInboxThreads("ahmed", false, {
      cursor: "page-2",
      category: "complaint",
      priority: "high",
      important: true,
      limit: 100,
    });

    expect(page.threads).toHaveLength(1);
    expect(page.total).toBe(42);
    expect(page.next_cursor).toBe("next-page");
    const url = urls[0];
    expect(url).toContain("search=ahmed");
    expect(url).toContain("cursor=page-2");
    expect(url).toContain("category=complaint");
    expect(url).toContain("priority=high");
    expect(url).toContain("important=true");
    expect(url).toContain("limit=100");
  });
});
