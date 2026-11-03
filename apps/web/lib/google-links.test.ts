import { describe, expect, it } from "vitest";
import {
  GBP_DASHBOARD_URL,
  listingMapsUrl,
  mapsPlaceUrl,
  safeMapsUrl,
} from "./google-links";

describe("mapsPlaceUrl", () => {
  it("builds the documented place_id link", () => {
    expect(mapsPlaceUrl("ChIJN1t_tDeuEmsRUsoyG83frY4")).toBe(
      "https://www.google.com/maps/place/?q=place_id:ChIJN1t_tDeuEmsRUsoyG83frY4",
    );
  });

  it("encodes opaque ids", () => {
    expect(mapsPlaceUrl("abc/def?x=1")).toBe(
      "https://www.google.com/maps/place/?q=place_id:abc%2Fdef%3Fx%3D1",
    );
  });

  it("rejects empty, whitespace, and control characters", () => {
    expect(mapsPlaceUrl(null)).toBeNull();
    expect(mapsPlaceUrl("   ")).toBeNull();
    expect(mapsPlaceUrl("abc def")).toBeNull();
    expect(mapsPlaceUrl("abc\u0000def")).toBeNull();
  });
});

describe("safeMapsUrl", () => {
  it("accepts real Google Maps URLs", () => {
    expect(safeMapsUrl("https://maps.google.com/?cid=123")).toBe(
      "https://maps.google.com/?cid=123",
    );
    expect(safeMapsUrl("https://www.google.com/maps/place/Foo/@1,2,3z")).toBe(
      "https://www.google.com/maps/place/Foo/@1,2,3z",
    );
    expect(safeMapsUrl("https://maps.app.goo.gl/abc123")).toBe(
      "https://maps.app.goo.gl/abc123",
    );
  });

  it("rejects non-Google, non-https, and script-capable URLs", () => {
    expect(safeMapsUrl("https://example.com/maps/place/1")).toBeNull();
    expect(safeMapsUrl("http://maps.google.com/?cid=1")).toBeNull();
    expect(safeMapsUrl("javascript:alert(1)")).toBeNull();
    expect(safeMapsUrl("https://www.google.com/search?q=sayvors")).toBeNull();
    expect(safeMapsUrl("https://google.com.evil/maps/place/1")).toBeNull();
    expect(safeMapsUrl("https://www.google.com.sa/maps/place/1")).toBeNull();
    expect(safeMapsUrl("")).toBeNull();
    expect(safeMapsUrl(null)).toBeNull();
  });
});

describe("listingMapsUrl", () => {
  it("prefers the stored Maps URL", () => {
    expect(
      listingMapsUrl({
        mapsUrl: "https://maps.google.com/?cid=123",
        placeId: "ChIJabc",
      }),
    ).toBe("https://maps.google.com/?cid=123");
  });

  it("falls back to the place id", () => {
    expect(listingMapsUrl({ mapsUrl: "https://example.com", placeId: "ChIJabc" })).toBe(
      "https://www.google.com/maps/place/?q=place_id:ChIJabc",
    );
  });

  it("returns null when neither identifier is usable", () => {
    expect(listingMapsUrl({})).toBeNull();
    expect(listingMapsUrl({ mapsUrl: "javascript:alert(1)" })).toBeNull();
  });
});

describe("GBP dashboard", () => {
  it("is a real HTTPS destination", () => {
    expect(GBP_DASHBOARD_URL).toBe("https://business.google.com/locations");
  });
});
