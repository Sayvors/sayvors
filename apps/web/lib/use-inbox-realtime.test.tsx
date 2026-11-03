import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useInboxRealtime } from "./use-inbox-realtime";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static reset() {
    FakeWebSocket.instances = [];
  }

  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;

  readyState = this.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  open() {
    this.readyState = this.OPEN;
    this.onopen?.();
  }

  emit(data: unknown) {
    this.onmessage?.({
      data: JSON.stringify(data),
    } as MessageEvent<string>);
  }

  close() {
    if (this.readyState === this.CLOSED) return;
    this.readyState = this.CLOSED;
    this.onclose?.();
  }
}

function setNavigatorOnline(online: boolean) {
  Object.defineProperty(window.navigator, "onLine", {
    configurable: true,
    get: () => online,
  });
}

describe("useInboxRealtime", () => {
  beforeEach(() => {
    FakeWebSocket.reset();
    vi.useFakeTimers();
    setNavigatorOnline(true);
    vi.stubGlobal("WebSocket", FakeWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("ignores ping frames", () => {
    const events: unknown[] = [];
    const { unmount } = renderHook(() =>
      useInboxRealtime((event) => events.push(event)),
    );

    const ws = FakeWebSocket.instances[0];
    ws.open();
    ws.emit({ type: "ping" });

    expect(events).toHaveLength(0);
    unmount();
  });

  it("forwards non-ping frames", () => {
    const events: unknown[] = [];
    const { unmount } = renderHook(() =>
      useInboxRealtime((event) => events.push(event)),
    );

    const ws = FakeWebSocket.instances[0];
    ws.open();
    ws.emit({ type: "notification", notification: { kind: "message" } });

    expect(events).toEqual([
      { type: "notification", notification: { kind: "message" } },
    ]);
    unmount();
  });

  it("drops a half-open socket after three missed heartbeats", () => {
    const { unmount } = renderHook(() => useInboxRealtime(() => undefined));
    const ws = FakeWebSocket.instances[0];
    ws.open();
    const close = vi.spyOn(ws, "close");

    // The hook checks every 15s; pings stop, so the 75s timeout expires.
    vi.advanceTimersByTime(95_000);

    expect(close).toHaveBeenCalledOnce();
    expect(ws.readyState).toBe(ws.CLOSED);
    unmount();
  });

  it("waits for the browser to come back online instead of reconnecting in a loop", () => {
    const { unmount } = renderHook(() => useInboxRealtime(() => undefined));
    const first = FakeWebSocket.instances[0];
    first.open();

    setNavigatorOnline(false);
    window.dispatchEvent(new Event("offline"));
    vi.advanceTimersByTime(120_000);

    expect(FakeWebSocket.instances).toHaveLength(1);

    setNavigatorOnline(true);
    window.dispatchEvent(new Event("online"));

    expect(FakeWebSocket.instances).toHaveLength(2);
    unmount();
  });
});
