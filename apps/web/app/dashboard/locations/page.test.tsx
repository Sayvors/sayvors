import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

const api = vi.hoisted(() => ({
  fetch: vi.fn(),
}));

const query = vi.hoisted(() => ({
  refetch: vi.fn(),
  setQueryData: vi.fn(),
  invalidateQueries: vi.fn(),
}));

const i18n = vi.hoisted(() => ({ locale: "en" }));

vi.mock("@/lib/api-rag", () => ({
  apiFetch: api.fetch,
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: vi.fn(),
  useQueryClient: () => query,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/components/locations/LocationPinMap", () => ({ default: () => null }));
vi.mock("@/components/locations/BulkEditSheet", () => ({ default: () => null }));
vi.mock("@/components/LogoLoader", () => ({ default: () => null }));

vi.mock("@/lib/i18n/I18nProvider", async () => {
  const actual = await vi.importActual<typeof import("@/lib/i18n/I18nProvider")>(
    "@/lib/i18n/I18nProvider",
  );
  const en = await vi.importActual<typeof import("@/lib/i18n/en")>("@/lib/i18n/en");
  const ar = await vi.importActual<typeof import("@/lib/i18n/ar")>("@/lib/i18n/ar");
  return {
    ...actual,
    useI18n: () => ({
      locale: i18n.locale,
      dir: i18n.locale === "ar" ? "rtl" : "ltr",
      t: i18n.locale === "ar" ? ar.default : en.default,
    }),
  };
});

import { useQuery } from "@tanstack/react-query";
import LocationsPage from "./page";

const locations = [
  {
    listing_id: "branch-1",
    name: "Al Malqa",
    address: "Riyadh",
    phone: "+966 11 111 1111",
    website: "https://example.com",
    status: "active",
    is_verified: true,
  },
  {
    listing_id: "branch-2",
    name: "Makkah",
    address: "Makkah",
    phone: "+966 12 222 2222",
    website: "https://example.org",
    status: "active",
    is_verified: false,
  },
];

function profile(listingId: string, statuses: Record<string, { stage: string }>) {
  return {
    listing_id: listingId,
    name: listingId === "branch-1" ? "Al Malqa" : "Makkah",
    address: listingId === "branch-1" ? "Riyadh" : "Makkah",
    phone: listingId === "branch-1" ? "+966 11 111 1111" : "+966 12 222 2222",
    website: listingId === "branch-1" ? "https://example.com" : "https://example.org",
    status: "active",
    is_verified: listingId === "branch-1",
    categories: {},
    hours: {},
    service_area: [],
    attributes: {},
    google_synced: [],
    google_status: statuses,
    google_current: {
      phone: "+966 50 000 0000",
      website: "https://old.example.com",
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const listQueryData = {
  locations: locations.map((location) => ({
    id: location.listing_id,
    name: location.name,
    address: location.address,
    status: location.status,
    is_verified: location.is_verified,
  })),
  snapshots: Object.fromEntries(locations.map((location) => [location.listing_id, location])),
  snapshot: locations[0],
  selectedId: locations[0].listing_id,
};

beforeEach(() => {
  vi.clearAllMocks();
  i18n.locale = "en";
  query.refetch.mockResolvedValue(undefined);
  query.setQueryData.mockResolvedValue(undefined);
  query.invalidateQueries.mockResolvedValue(undefined);

  vi.mocked(useQuery).mockImplementation(({ queryKey }) => {
    if (queryKey[1] === "list") {
      return {
        data: listQueryData,
        isError: false,
        refetch: query.refetch,
      } as never;
    }
    return { data: undefined, isError: false, refetch: query.refetch } as never;
  });

  api.fetch.mockImplementation(async (url: string) => {
    if (url === "/api/v1/locations/groups") return [];
    if (url === "/api/v1/locations/branch-1") {
      return profile("branch-1", { phone: { stage: "pending" } });
    }
    if (url === "/api/v1/locations/branch-2") {
      return profile("branch-2", { website: { stage: "pending" } });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
});

describe("bulk location Google pending state", () => {
  it("shows pending sections and the branches waiting on Google", async () => {
    render(<LocationsPage />);

    const scope = screen.getAllByRole("combobox")[0];
    fireEvent.change(scope, { target: { value: "__all__" } });

    await waitFor(() => {
      expect(api.fetch).toHaveBeenCalledWith("/api/v1/locations/branch-1");
      expect(api.fetch).toHaveBeenCalledWith("/api/v1/locations/branch-2");
    });
    expect(await screen.findByText("Pending on Google")).toBeInTheDocument();
    const phone = screen.getByRole("button", { name: /Phone/ });
    const website = screen.getByRole("button", { name: /Website/ });
    expect(phone).toHaveTextContent("Al Malqa");
    expect(website).toHaveTextContent("Makkah");
    expect(phone).toHaveAttribute(
      "title",
      expect.stringContaining("Al Malqa"),
    );
    expect(website).toHaveAttribute(
      "title",
      expect.stringContaining("Makkah"),
    );
  });

  it("renders pending branch names with logical RTL-safe alignment", async () => {
    i18n.locale = "ar";
    render(<LocationsPage />);
    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "__all__" },
    });

    const phone = await screen.findByRole("button", { name: /الهاتف/ });
    const branchNames = within(phone).getByText("Al Malqa");
    expect(branchNames).toHaveClass("text-start");
    expect(branchNames).toHaveClass("break-words");
  });

  it("counts distinct pending branches even when their names match", async () => {
    const sameNameLocations = locations.map((location) => ({
      ...location,
      name: "Acme",
    }));
    const sameNameListQueryData = {
      locations: sameNameLocations.map((location) => ({
        id: location.listing_id,
        name: location.name,
        address: location.address,
        status: location.status,
        is_verified: location.is_verified,
      })),
      snapshots: Object.fromEntries(
        sameNameLocations.map((location) => [location.listing_id, location]),
      ),
      snapshot: sameNameLocations[0],
      selectedId: sameNameLocations[0].listing_id,
    };
    vi.mocked(useQuery).mockImplementation(({ queryKey }) => {
      if (queryKey[1] === "list") {
        return {
          data: sameNameListQueryData,
          isError: false,
          refetch: query.refetch,
        } as never;
      }
      return { data: undefined, isError: false, refetch: query.refetch } as never;
    });
    api.fetch.mockImplementation(async (url: string) => {
      if (url === "/api/v1/locations/groups") return [];
      if (url === "/api/v1/locations/branch-1") {
        return profile("branch-1", { phone: { stage: "pending" } });
      }
      if (url === "/api/v1/locations/branch-2") {
        return profile("branch-2", { phone: { stage: "pending" } });
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<LocationsPage />);
    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "__all__" },
    });

    const phone = await screen.findByRole("button", { name: /Phone/ });
    expect(within(phone).getByText("2")).toBeInTheDocument();
    expect(phone).toHaveTextContent("Acme, Acme");
  });

  it("does not let a stale initial profile response erase newly pending state", async () => {
    const initialBranchOne = deferred<ReturnType<typeof profile>>();
    const initialBranchTwo = deferred<ReturnType<typeof profile>>();
    let initialReads = 0;
    let saved = false;
    api.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/locations/groups") return [];
      if (url === "/api/v1/locations") return locations;
      if (url === "/api/v1/locations/branch-1") {
        if (init?.method === "PUT") {
          saved = true;
          return profile("branch-1", { phone: { stage: "pending" } });
        }
        if (!saved && initialReads === 0) {
          initialReads++;
          return initialBranchOne.promise;
        }
        return profile("branch-1", saved ? { phone: { stage: "pending" } } : {});
      }
      if (url === "/api/v1/locations/branch-2") {
        if (!saved && initialReads === 1) {
          initialReads++;
          return initialBranchTwo.promise;
        }
        return profile("branch-2", {});
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<LocationsPage />);
    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "__all__" },
    });
    await waitFor(() => expect(initialReads).toBe(2));

    fireEvent.click(
      screen.getByText("Edit your location's core information.").closest("button")!,
    );
    fireEvent.change(screen.getByPlaceholderText("+966 55 000 0000"), {
      target: { value: "+966 55 123 4567" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply to 2 branches" }));
    const dialog = screen.getByRole("alertdialog", { name: "Confirm bulk edit" });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Apply to 2 branches" }),
    );

    expect(await screen.findByText("Pending on Google")).toBeInTheDocument();
    await act(async () => {
      initialBranchOne.resolve(profile("branch-1", {}));
      initialBranchTwo.resolve(profile("branch-2", {}));
    });
    expect(screen.getByText("Pending on Google")).toBeInTheDocument();
  });

  it.each([
    {
      locale: "en",
      warning: /Google status could not be refreshed for Al Malqa/,
      detailsSubtitle: "Edit your location's core information.",
      applyLabel: "Apply to 2 branches",
    },
    {
      locale: "ar",
      warning: /تعذّر تحديث حالة Google للفروع: Al Malqa/,
      detailsSubtitle: "عدّل المعلومات الأساسية لفرعك.",
      applyLabel: "تطبيق على 2 فروع",
    },
  ])(
    "warns when a bulk save succeeds but status refresh fails ($locale)",
    async ({ locale, warning, detailsSubtitle, applyLabel }) => {
    i18n.locale = locale;
    let saved = false;
    api.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/locations/groups") return [];
      if (url === "/api/v1/locations") return locations;
      if (url === "/api/v1/locations/branch-1") {
        if (init?.method === "PUT") {
          saved = true;
          return profile("branch-1", { phone: { stage: "pending" } });
        }
        if (saved) throw new Error("status refresh failed");
        return profile("branch-1", {});
      }
      if (url === "/api/v1/locations/branch-2") {
        return profile("branch-2", {});
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<LocationsPage />);
    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "__all__" },
    });
    await waitFor(() => {
      expect(api.fetch).toHaveBeenCalledWith("/api/v1/locations/branch-1");
      expect(api.fetch).toHaveBeenCalledWith("/api/v1/locations/branch-2");
    });

    fireEvent.click(
      screen.getByText(detailsSubtitle).closest("button")!,
    );
    fireEvent.change(screen.getByPlaceholderText("+966 55 000 0000"), {
      target: { value: "+966 55 123 4567" },
    });
    fireEvent.click(screen.getByRole("button", { name: applyLabel }));
    const dialog = screen.getByRole("alertdialog", { name: "Confirm bulk edit" });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Apply to 2 branches" }),
    );

    expect(await screen.findByText(warning)).toBeInTheDocument();
  });

  it("refreshes per-branch pending state after a bulk details save", async () => {
    let saved = false;
    api.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url === "/api/v1/locations/groups") return [];
      if (url === "/api/v1/locations") return locations;
      if (url === "/api/v1/locations/branch-1") {
        if (init?.method === "PUT") {
          saved = true;
          return profile("branch-1", { phone: { stage: "pending" } });
        }
        return profile("branch-1", saved ? { phone: { stage: "pending" } } : {});
      }
      if (url === "/api/v1/locations/branch-2") {
        return profile("branch-2", {});
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<LocationsPage />);
    fireEvent.change(screen.getAllByRole("combobox")[0], {
      target: { value: "__all__" },
    });
    await waitFor(() => {
      expect(api.fetch).toHaveBeenCalledWith("/api/v1/locations/branch-1");
      expect(api.fetch).toHaveBeenCalledWith("/api/v1/locations/branch-2");
    });
    const initialBranchOneReads = api.fetch.mock.calls.filter(
      ([url, init]) =>
        url === "/api/v1/locations/branch-1" && init?.method !== "PUT",
    ).length;

    fireEvent.click(
      screen.getByText("Edit your location's core information.").closest("button")!,
    );
    fireEvent.change(screen.getByPlaceholderText("+966 55 000 0000"), {
      target: { value: "+966 55 123 4567" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply to 2 branches" }));
    const dialog = screen.getByRole("alertdialog", { name: "Confirm bulk edit" });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Apply to 2 branches" }),
    );

    await waitFor(() => {
      const branchOneReads = api.fetch.mock.calls.filter(
        ([url, init]) =>
          url === "/api/v1/locations/branch-1" && init?.method !== "PUT",
      );
      expect(branchOneReads.length).toBeGreaterThan(initialBranchOneReads);
    });
    expect(await screen.findByText("Pending on Google")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Phone/ })).toHaveAttribute(
      "title",
      expect.stringContaining("Al Malqa"),
    );
  });
});
