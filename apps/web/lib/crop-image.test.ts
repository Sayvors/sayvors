import { describe, expect, it } from "vitest";
import { CROP_EDITOR_BOX, cropSignature, cropSourceRect } from "./crop-image";

/*
 * These pin the framing contract between CropFrame (the preview) and the
 * canvas that bakes the file sent to a provider. A drift here is invisible
 * in the UI and only shows up as a wrongly framed published photo.
 */

const square = { key: "1:1", zoom: 1, x: 0, y: 0 } as const;

describe("cropSourceRect", () => {
  it("takes a centred square out of a landscape photo", () => {
    expect(cropSourceRect(900, 600, square)).toEqual({
      x: 150,
      y: 0,
      w: 600,
      h: 600,
    });
  });

  it("moves the window opposite the image when the frame is panned", () => {
    // Dragging the image 50px left is the editor's clamp for this photo and
    // reveals the right edge: the source window starts at x=300.
    expect(cropSourceRect(900, 600, { ...square, x: -50 })).toEqual({
      x: 300,
      y: 0,
      w: 600,
      h: 600,
    });
  });

  it("zooming in shrinks the window around the same centre", () => {
    expect(cropSourceRect(900, 600, { ...square, zoom: 2 })).toEqual({
      x: 300,
      y: 150,
      w: 300,
      h: 300,
    });
  });

  it("uses the same box height as the editor for each ratio", () => {
    // The editor rounds its on-screen box height, and the export has to
    // match that box exactly rather than an idealised 16:9.
    expect(CROP_EDITOR_BOX).toBe(200);
    const portrait = cropSourceRect(900, 600, {
      key: "4:5",
      zoom: 1,
      x: 0,
      y: 0,
    });
    expect(portrait).toEqual({ x: 210, y: 0, w: 480, h: 600 });

    const landscape = cropSourceRect(900, 600, {
      key: "16:9",
      zoom: 1,
      x: 0,
      y: 0,
    });
    expect(landscape).not.toBeNull();
    expect(landscape!.x).toBe(0);
    expect(landscape!.w).toBe(900);
    expect(landscape!.y).toBeCloseTo(45.75, 5);
    expect(landscape!.h).toBeCloseTo(508.5, 5);
  });

  it("returns null for the original, which is published untouched", () => {
    expect(cropSourceRect(900, 600, { ...square, key: "orig" })).toBeNull();
  });

  it("refuses an offset that puts the whole frame outside the image", () => {
    expect(() => cropSourceRect(900, 600, { ...square, x: -9999 })).toThrow(
      "outside the image",
    );
  });
});

describe("cropSignature", () => {
  it("bundles the same framing to one upload", () => {
    expect(cropSignature({ key: "1:1", zoom: 1, x: 10.4, y: -2.6 })).toBe(
      cropSignature({ key: "1:1", zoom: 1, x: 10, y: -3 }),
    );
  });

  it("separates different ratios and zooms", () => {
    const base = cropSignature(square);
    expect(cropSignature({ ...square, key: "4:5" })).not.toBe(base);
    expect(cropSignature({ ...square, zoom: 1.5 })).not.toBe(base);
  });
});
