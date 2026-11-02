import { describe, expect, it } from "vitest";
import { safeHref } from "./safe-url";

describe("safeHref", () => {
  it("allows http, https, and mailto links", () => {
    expect(safeHref("https://example.com/path?q=1")).toBe("https://example.com/path?q=1");
    expect(safeHref("http://example.com")).toBe("http://example.com");
    expect(safeHref("mailto:hello@example.com")).toBe("mailto:hello@example.com");
    expect(safeHref("HTTPS://EXAMPLE.COM")).toBe("HTTPS://EXAMPLE.COM");
  });

  it("blocks script-capable and unknown schemes", () => {
    expect(safeHref("javascript:alert(document.cookie)")).toBeNull();
    expect(safeHref("JaVaScRiPt:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeHref("vbscript:msgbox(1)")).toBeNull();
    expect(safeHref("file:///etc/passwd")).toBeNull();
    expect(safeHref("blob:https://example.com/id")).toBeNull();
  });

  it("rejects control characters that browsers strip into a live scheme", () => {
    expect(safeHref("java\nscript:alert(1)")).toBeNull();
    expect(safeHref("java\tscript:alert(1)")).toBeNull();
    expect(safeHref("javascript\u0000:alert(1)")).toBeNull();
  });

  it("allows relative navigation because it cannot execute script", () => {
    expect(safeHref("/dashboard/reviews")).toBe("/dashboard/reviews");
    expect(safeHref("dashboard/reviews")).toBe("dashboard/reviews");
    expect(safeHref("#section")).toBe("#section");
    expect(safeHref("?tab=insights")).toBe("?tab=insights");
    expect(safeHref("//example.com/path")).toBe("//example.com/path");
  });

  it("rejects empty and malformed values", () => {
    expect(safeHref("")).toBeNull();
    expect(safeHref("   ")).toBeNull();
    expect(safeHref("https://")).toBeNull();
  });
});
