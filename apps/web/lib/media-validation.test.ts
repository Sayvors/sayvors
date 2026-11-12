import { describe, it, expect } from "vitest";
import {
  validateMediaFile,
  validateImageDimensions,
  validateSchedule,
  wallTimeToInstant,
  validateMediaUrl,
  kindOfFile,
  MAX_UPLOAD_BYTES,
  MAX_GOOGLE_PHOTO_BYTES,
  MIN_GOOGLE_EDGE,
} from "./media-validation";

describe("media-validation", () => {
  it("rejects oversized uploads", () => {
    const f = new File([new ArrayBuffer(MAX_UPLOAD_BYTES + 1)], "big.jpg", { type: "image/jpeg" });
    const issues = validateMediaFile(f, "post");
    expect(issues.some((i) => i.level === "error" && /too large/i.test(i.message))).toBe(true);
  });

  it("rejects unknown file types", () => {
    const f = new File(["x"], "x.txt", { type: "text/plain" });
    const issues = validateMediaFile(f, "post");
    expect(issues.some((i) => i.level === "error")).toBe(true);
  });

  it("rejects video for non-post methods", () => {
    const f = new File([new ArrayBuffer(10)], "v.mp4", { type: "video/mp4" });
    const issues = validateMediaFile(f, "gallery");
    expect(issues.some((i) => i.level === "error" && /Google post/i.test(i.message))).toBe(true);
  });

  it("rejects photos over 5MB for gallery", () => {
    const f = new File([new ArrayBuffer(MAX_GOOGLE_PHOTO_BYTES + 100)], "p.jpg", { type: "image/jpeg" });
    const issues = validateMediaFile(f, "gallery");
    expect(issues.some((i) => i.level === "error" && /5MB/i.test(i.message))).toBe(true);
  });

  it("flags images below 250px", () => {
    const issues = validateImageDimensions({ width: 100, height: 100 }, "post");
    expect(issues.some((i) => i.level === "error" && /too small/i.test(i.message))).toBe(true);
  });

  it("warns about non-square profile pictures", () => {
    const issues = validateImageDimensions({ width: 400, height: 300 }, "profile");
    expect(issues.some((i) => i.level === "warning" && /circle/i.test(i.message))).toBe(true);
  });

  it("treats wall time as Riyadh (UTC+3)", () => {
    const d = wallTimeToInstant("2026-11-13T10:00");
    expect(d?.toISOString()).toBe("2026-11-13T07:00:00.000Z");
  });

  it("rejects past schedule", () => {
    const past = new Date(Date.now() - 60_000).toISOString().slice(0, 16).replace("T", "T");
    // build a Riyadh wall value in the past
    const issues = validateSchedule("2020-01-01T10:00");
    expect(issues.some((i) => i.level === "error")).toBe(true);
  });

  it("validates URLs", () => {
    expect(validateMediaUrl("not a url").some((i) => i.level === "error")).toBe(true);
    expect(validateMediaUrl("https://example.com/a.jpg").some((i) => i.level === "error")).toBe(false);
  });

  it("detects kind from file", () => {
    const f = new File(["x"], "a.PNG", { type: "" });
    expect(kindOfFile(f)).toBe("image");
  });

  it("min google edge constant", () => {
    expect(MIN_GOOGLE_EDGE).toBe(250);
  });
});
