import { describe, expect, it } from "vitest";

import {
  defaultCompareMain,
  sortCompareChannels,
  type CompareChannelOption,
} from "./benchmark-selection";

const channels: CompareChannelOption[] = [
  {
    id: "unverified",
    display_name: "Alpha Branch",
    platform: "google_reviews",
    status: "active",
    verification_status: "pending",
    verified: false,
  },
  {
    id: "verified",
    display_name: "Zulu Branch",
    platform: "google_reviews",
    status: "active",
    verification_status: "verified",
    verified: true,
  },
];

describe("benchmark channel selection", () => {
  it("sorts verified branches first without mutating the API order", () => {
    const sorted = sortCompareChannels(channels);
    expect(sorted.map((channel) => channel.id)).toEqual(["verified", "unverified"]);
    expect(channels.map((channel) => channel.id)).toEqual(["unverified", "verified"]);
  });

  it("defaults to the first verified branch", () => {
    expect(defaultCompareMain(channels)).toBe("own:verified");
  });

  it("does not default to an unverified branch", () => {
    expect(defaultCompareMain([channels[0]])).toBeNull();
    expect(defaultCompareMain([])).toBeNull();
  });
});
