import { describe, it, expect } from "vitest";
import {
  validateMediaFile,
  validateImageDimensions,
  validateSchedule,
  wallTimeToInstant,
  validateMediaUrl,
  kindOfFile,
  sniffFileFormat,
  normalizePickedFile,
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

  describe("sniffFileFormat + normalizePickedFile", () => {
    const strBytes = (s: string) => Array.from(s, (c) => c.charCodeAt(0));
    const file = (chunks: Uint8Array[], name: string) => new File(chunks as BlobPart[], name);

    it("reads the real format from magic bytes, not the name", async () => {
      const jpegNamedWebp = file([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0, 0])], "a.webp");
      expect(await sniffFileFormat(jpegNamedWebp)).toBe("jpeg");
      const pngNamedJpg = file([new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])], "a.jpg");
      expect(await sniffFileFormat(pngNamedJpg)).toBe("png");
      const webp = file([
        new Uint8Array([...strBytes("RIFF"), 0, 0, 0, 0, ...strBytes("WEBP")]),
      ], "b.png");
      expect(await sniffFileFormat(webp)).toBe("webp");
      const heic = file([
        new Uint8Array([0, 0, 0, 24, ...strBytes("ftyp"), ...strBytes("heic"), 0, 0, 0, 0]),
      ], "c.mov");
      expect(await sniffFileFormat(heic)).toBe("heic");
    });

    it("renames a lying extension so the publish upload passes", async () => {
      // WebP bytes carried as .jpg are rejected by the storage layer's
      // magic check; normalization must fix the name before upload.
      const webp = file([
        new Uint8Array([...strBytes("RIFF"), 0, 0, 0, 0, ...strBytes("WEBP")]),
      ], "photo.jpg");
      const norm = await normalizePickedFile(webp);
      expect(norm.ok).toBe(true);
      if (norm.ok) {
        expect(norm.file.name).toBe("photo.webp");
        expect(norm.note).toBeTruthy();
      }
    });

    it("keeps an honest file untouched", async () => {
      const jpeg = file([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], "keep.jpg");
      const norm = await normalizePickedFile(jpeg);
      expect(norm.ok).toBe(true);
      if (norm.ok) expect(norm.note).toBeUndefined();
    });

    it("rejects unreadable bytes with a plain-language fix", async () => {
      const junk = file([new Uint8Array([1, 2, 3, 4, 5])], "junk.jpg");
      const norm = await normalizePickedFile(junk);
      expect(norm.ok).toBe(false);
      if (!norm.ok) expect(norm.error).toMatch(/JPG or PNG/);
    });

    it("fails clearly on HEIC when the browser cannot convert it", async () => {
      const heic = file([
        new Uint8Array([0, 0, 0, 24, ...strBytes("ftyp"), ...strBytes("heic"), 0, 0, 0, 0]),
      ], "img.heic");
      const norm = await normalizePickedFile(heic);
      // jsdom has no createImageBitmap, so conversion is impossible here;
      // the merchant must get the "export as JPG" instruction, not a
      // cryptic publish failure later.
      expect(norm.ok).toBe(false);
      if (!norm.ok) expect(norm.error).toMatch(/HEIC|AVIF/);
    });
  });
});
