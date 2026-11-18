import { beforeEach, describe, expect, it, vi } from "vitest";

const apiFetch = vi.fn();

vi.mock("@/lib/api-rag", () => ({
  apiFetch: (...args: unknown[]) => apiFetch(...args),
}));

/** Each case gets a fresh module so the per-document cache starts empty. */
async function fresh() {
  vi.resetModules();
  return import("./permissions");
}

beforeEach(() => {
  apiFetch.mockReset();
});

describe("hasPermission", () => {
  it("grants everything to an owner whose permission list is empty", async () => {
    // Owners are never stored as members, so the API sends is_owner with an
    // empty list. Reading the list alone would hide owner affordances.
    apiFetch.mockResolvedValue({ is_owner: true, permissions: [], channel_overrides: {} });
    const { hasPermission } = await fresh();
    await expect(hasPermission("reviews.reply")).resolves.toBe(true);
  });

  it("follows the member's permission list", async () => {
    apiFetch.mockResolvedValue({
      is_owner: false,
      permissions: ["reviews.view", "reviews.reply"],
      channel_overrides: {},
    });
    const { hasPermission } = await fresh();
    await expect(hasPermission("reviews.reply")).resolves.toBe(true);
    await expect(hasPermission("billing.manage")).resolves.toBe(false);
  });

  it("shares one request between concurrent callers", async () => {
    apiFetch.mockResolvedValue({ is_owner: false, permissions: ["reviews.reply"] });
    const { hasPermission } = await fresh();
    await Promise.all([
      hasPermission("reviews.reply"),
      hasPermission("reviews.reply"),
      hasPermission("reviews.view"),
    ]);
    expect(apiFetch).toHaveBeenCalledTimes(1);
  });

  it("fails closed when the context cannot be loaded", async () => {
    apiFetch.mockRejectedValue(new Error("network"));
    const { hasPermission } = await fresh();
    await expect(hasPermission("reviews.reply")).resolves.toBe(false);
  });

  it("retries after a failed load instead of pinning the page to no access", async () => {
    apiFetch
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ is_owner: false, permissions: ["reviews.reply"] });
    const { hasPermission } = await fresh();
    await expect(hasPermission("reviews.reply")).resolves.toBe(false);
    await expect(hasPermission("reviews.reply")).resolves.toBe(true);
    expect(apiFetch).toHaveBeenCalledTimes(2);
  });
});
