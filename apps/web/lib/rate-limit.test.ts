import { describe, expect, it } from "vitest";
import { SlidingWindowLimiter } from "./rate-limit";

describe("SlidingWindowLimiter", () => {
  it("allows up to the limit and denies the next request", () => {
    const limiter = new SlidingWindowLimiter(60_000, 100);

    expect(limiter.allow("ip", 3, 1_000)).toBe(true);
    expect(limiter.allow("ip", 3, 1_000)).toBe(true);
    expect(limiter.allow("ip", 3, 1_000)).toBe(true);
    expect(limiter.allow("ip", 3, 1_000)).toBe(false);
  });

  it("resets when the window elapses", () => {
    const limiter = new SlidingWindowLimiter(1_000, 100);

    expect(limiter.allow("ip", 1, 0)).toBe(true);
    expect(limiter.allow("ip", 1, 500)).toBe(false);
    // The window slides from the last request, so the reset is after 500 + 1000.
    expect(limiter.allow("ip", 1, 1_501)).toBe(true);
  });

  it("prunes expired keys instead of growing forever", () => {
    const limiter = new SlidingWindowLimiter(1_000, 100);
    limiter.allow("old", 1, 0);

    limiter.allow("fresh", 1, 1_001);

    expect(limiter.size).toBe(1);
  });

  it("bounds the map and evicts the least recently used key", () => {
    const limiter = new SlidingWindowLimiter(60_000, 2);
    limiter.allow("a", 10, 1_000);
    limiter.allow("b", 10, 1_000);
    limiter.allow("a", 10, 1_000); // refresh a
    limiter.allow("c", 10, 1_000); // evict b

    expect(limiter.size).toBe(2);
    // b was evicted, so it starts from a clean count; if it had survived,
    // this would be its second request against a limit of 1.
    expect(limiter.allow("b", 1, 1_000)).toBe(true);
    expect(limiter.size).toBe(2);
  });
});
