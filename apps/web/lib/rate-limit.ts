/**
 * Best-effort, bounded sliding-window limiter for the Next edge middleware.
 *
 * This is deliberately not a security control: the key is a client-supplied
 * address, each replica has its own map, and a limiter failure always allows
 * the request. It exists to stop a single source from hammering page/RSC/media
 * traffic; the API backend owns the real auth and rate limits.
 */
export interface RateLimitEntry {
  count: number;
  last: number;
}

export class SlidingWindowLimiter {
  private entries = new Map<string, RateLimitEntry>();
  private lastPrune = 0;

  constructor(
    private readonly windowMs: number,
    private readonly maxKeys: number,
  ) {}

  /** True when this request is within the window's allowance. */
  allow(key: string, limit: number, now = Date.now()): boolean {
    this.prune(now);

    const entry = this.entries.get(key);
    if (entry && now - entry.last <= this.windowMs) {
      entry.count += 1;
      entry.last = now;
      // Refresh recency: eviction removes the oldest insertion from the front.
      this.entries.delete(key);
      this.entries.set(key, entry);
      return entry.count <= limit;
    }

    this.entries.set(key, { count: 1, last: now });
    return limit >= 1;
  }

  get size(): number {
    return this.entries.size;
  }

  private prune(now: number): void {
    const windowElapsed = now - this.lastPrune >= this.windowMs;
    if (!windowElapsed && this.entries.size < this.maxKeys) return;

    this.lastPrune = now;
    for (const [key, entry] of this.entries) {
      if (now - entry.last > this.windowMs) {
        this.entries.delete(key);
      }
    }
    // A spoofed/rotating address must not grow the map without bound. Map
    // preserves insertion order, and allow() refreshes recency on use, so
    // deleting from the front evicts the least recently used key.
    while (this.entries.size >= this.maxKeys) {
      const oldest = this.entries.keys().next().value;
      if (oldest === undefined) break;
      this.entries.delete(oldest);
    }
  }
}
