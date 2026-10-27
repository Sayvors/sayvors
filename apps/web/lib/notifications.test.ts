import { describe, it, expect, beforeEach } from "vitest";
import {
  pillKindFor,
  notifyPill,
  subscribePills,
  loadSeenIds,
  rememberSeenIds,
  PILL_META,
} from "./notifications";

describe("pillKindFor", () => {
  it("maps review_pulled to pulled", () => {
    expect(pillKindFor("review_pulled")).toBe("pulled");
  });
  it("maps reply_failed/post_failed/media_failed to failed", () => {
    expect(pillKindFor("reply_failed")).toBe("failed");
    expect(pillKindFor("post_failed")).toBe("failed");
    expect(pillKindFor("media_failed")).toBe("failed");
  });
  it("maps review_ticket_created to ticket", () => {
    expect(pillKindFor("review_ticket_created")).toBe("ticket");
  });
  it("returns null for non-pill types", () => {
    expect(pillKindFor("sync_completed")).toBeNull();
    expect(pillKindFor("")).toBeNull();
    expect(pillKindFor("unknown_type")).toBeNull();
  });
});

describe("PILL_META", () => {
  it("has entries for all pill kinds", () => {
    expect(PILL_META.pulled).toBeDefined();
    expect(PILL_META.failed).toBeDefined();
    expect(PILL_META.ticket).toBeDefined();
  });
});

describe("notifyPill / subscribePills", () => {
  it("delivers pills to subscribers", () => {
    const received: string[] = [];
    const unsub = subscribePills((p) => received.push(p.text));
    notifyPill("hello", "pulled");
    expect(received).toEqual(["hello"]);
    unsub();
    notifyPill("after unsub", "failed");
    expect(received).toEqual(["hello"]);
  });

  it("does not throw when a listener throws", () => {
    const unsub = subscribePills(() => {
      throw new Error("boom");
    });
    expect(() => notifyPill("safe", "ticket")).not.toThrow();
    unsub();
  });

  it("assigns unique ids", () => {
    const ids: string[] = [];
    const unsub = subscribePills((p) => ids.push(p.id));
    notifyPill("a", "pulled");
    notifyPill("b", "failed");
    expect(ids).toHaveLength(2);
    expect(ids[0]).not.toBe(ids[1]);
    unsub();
  });
});

describe("loadSeenIds / rememberSeenIds", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("returns empty set when nothing stored", () => {
    expect(loadSeenIds().size).toBe(0);
  });

  it("round-trips a set of ids", () => {
    const ids = new Set(["a", "b", "c"]);
    rememberSeenIds(ids);
    const loaded = loadSeenIds();
    expect(loaded).toEqual(ids);
  });

  it("caps persisted ids to 60", () => {
    const ids = new Set(Array.from({ length: 100 }, (_, i) => `id-${i}`));
    rememberSeenIds(ids);
    const loaded = loadSeenIds();
    expect(loaded.size).toBe(60);
  });

  it("filters non-string entries", () => {
    window.localStorage.setItem("sayvors.notif.seen", JSON.stringify([1, "ok", null, "two"]));
    const loaded = loadSeenIds();
    expect(loaded).toEqual(new Set(["ok", "two"]));
  });

  it("returns empty set on corrupt JSON", () => {
    window.localStorage.setItem("sayvors.notif.seen", "{not json");
    expect(loadSeenIds().size).toBe(0);
  });
});
