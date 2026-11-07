"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import CategoryPicker from "@/components/locations/CategoryPicker";
import LocationPinMap, { type LatLng } from "@/components/locations/LocationPinMap";
import LogoLoader from "@/components/LogoLoader";
import { apiFetch } from "@/lib/api-rag";
import { COUNTRIES } from "@/lib/countries";
import { useI18n } from "@/lib/i18n/I18nProvider";

const STEPS = [
  { key: "basics", label: "Business", hint: "Name and category" },
  { key: "location", label: "Location", hint: "Storefront or service area" },
  { key: "address", label: "Address", hint: "Where customers find you" },
  { key: "contact", label: "Contact", hint: "Phone, website, description" },
  { key: "review", label: "Review", hint: "Check Google, then create" },
  { key: "verify", label: "Verify", hint: "Google verification" },
] as const;

const DRAFT_KEY = "sayvors.locationDraft.v2";
const MAPS_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY ?? "";
const MAX_SERVICE_AREAS = 20;

interface Draft {
  name: string;
  category: string;
  hasStorefront: boolean;
  delivers: boolean;
  street: string;
  city: string;
  state: string;
  postalCode: string;
  country: string;
  phone: string;
  website: string;
  description: string;
  serviceAreas: string[];
  pin: LatLng | null;
}

const EMPTY_DRAFT: Draft = {
  name: "",
  category: "",
  hasStorefront: true,
  delivers: false,
  street: "",
  city: "",
  state: "",
  postalCode: "",
  country: "SA",
  phone: "",
  website: "",
  description: "",
  serviceAreas: [],
  pin: null,
};

interface LocationMatch {
  name: string;
  location_name?: string | null;
  address?: string | null;
  place_id?: string | null;
  request_admin_rights_url?: string | null;
}

interface CreatedLocation {
  listing_id: string;
  channel_id: string;
  name: string;
  address: string | null;
  status: string;
  created: boolean;
}

function loadDraft(): Draft {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY);
    if (!raw) return { ...EMPTY_DRAFT };
    const parsed = JSON.parse(raw) as Partial<Draft>;
    return {
      ...EMPTY_DRAFT,
      ...parsed,
      serviceAreas: Array.isArray(parsed.serviceAreas) ? parsed.serviceAreas : [],
      pin:
        parsed.pin &&
        typeof parsed.pin.lat === "number" &&
        typeof parsed.pin.lng === "number"
          ? parsed.pin
          : null,
    };
  } catch {
    return { ...EMPTY_DRAFT };
  }
}

function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-[0.08em] text-ink/55 dark:text-fog/55">
        {label}
        {required ? " *" : ""}
      </span>
      {children}
      {hint && (
        <span className="mt-1 block text-[10.5px] leading-relaxed text-ink/40 dark:text-fog/40">
          {hint}
        </span>
      )}
    </label>
  );
}

export default function NewLocationPage() {
  const router = useRouter();
  const { locale } = useI18n();

  const [hydrated, setHydrated] = useState(false);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<string[]>([]);
  const [connection, setConnection] = useState<"checking" | "yes" | "no">("checking");

  const [matches, setMatches] = useState<LocationMatch[]>([]);
  const [matchLoading, setMatchLoading] = useState(false);
  const [matchError, setMatchError] = useState<string | null>(null);
  const matchSeq = useRef(0);

  const [duplicates, setDuplicates] = useState<LocationMatch[] | null>(null);
  const [duplicateLoading, setDuplicateLoading] = useState(false);
  const [duplicateError, setDuplicateError] = useState<string | null>(null);
  const duplicateSeq = useRef(0);

  const [areaInput, setAreaInput] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [created, setCreated] = useState<CreatedLocation | null>(null);
  const requestIdRef = useRef("");

  useEffect(() => {
    setDraft(loadDraft());
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      /* private mode */
    }
  }, [draft, hydrated]);

  useEffect(() => {
    let cancelled = false;
    apiFetch("/api/v1/channels?limit=100")
      .then((data) => {
        if (cancelled) return;
        const channels = ((data as { channels?: { platform?: string }[] }).channels ?? []);
        setConnection(
          channels.some((channel) => channel.platform === "google_reviews") ? "yes" : "no",
        );
      })
      .catch(() => {
        if (!cancelled) setConnection("no");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (step !== 0) return;
    const name = draft.name.trim();
    if (name.length < 3) {
      setMatches([]);
      setMatchError(null);
      setMatchLoading(false);
      return;
    }
    const timer = setTimeout(() => {
      const seq = ++matchSeq.current;
      setMatchLoading(true);
      setMatchError(null);
      apiFetch("/api/v1/locations/search", {
        method: "POST",
        body: JSON.stringify({
          name,
          category: draft.category.trim() || null,
          has_storefront: draft.hasStorefront,
        }),
      })
        .then((rows) => {
          if (seq !== matchSeq.current) return;
          setMatches(Array.isArray(rows) ? (rows as LocationMatch[]).slice(0, 5) : []);
        })
        .catch((error) => {
          if (seq !== matchSeq.current) return;
          setMatches([]);
          setMatchError(error instanceof Error ? error.message : "Google suggestions are unavailable.");
        })
        .finally(() => {
          if (seq === matchSeq.current) setMatchLoading(false);
        });
    }, 500);
    return () => clearTimeout(timer);
  }, [draft.name, draft.category, draft.hasStorefront, step]);

  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  const countryName =
    COUNTRIES.find((country) => country.code === draft.country)?.name ?? draft.country;
  const fullAddress = [
    draft.street,
    draft.city,
    draft.state,
    draft.postalCode,
    countryName,
  ]
    .map((part) => part.trim())
    .filter(Boolean)
    .join(", ");

  const validateStep = (index: number): string[] => {
    const missing: string[] = [];
    if (index === 0) {
      if (!draft.name.trim()) missing.push("Business name");
      if (!draft.category.trim()) missing.push("Primary category");
    }
    if (index === 2) {
      if (draft.hasStorefront) {
        if (!draft.street.trim()) missing.push("Street address");
        if (!draft.city.trim()) missing.push("City");
        if (draft.country.trim().length !== 2) missing.push("Country");
      } else if (draft.serviceAreas.length === 0) {
        missing.push("At least one service area");
      }
    }
    if (index === 3) {
      if (!draft.phone.trim()) missing.push("Phone");
      if (draft.website.trim() && !/^https?:\/\//i.test(draft.website.trim())) {
        missing.push("Website must start with http:// or https://");
      }
    }
    return missing;
  };

  const goNext = () => {
    const missing = validateStep(step);
    if (missing.length) {
      setErrors(missing);
      return;
    }
    setErrors([]);
    if (step === 3) {
      setStep(4);
      void runDuplicateCheck();
      return;
    }
    setStep((current) => Math.min(current + 1, STEPS.length - 1));
  };

  const goBack = () => {
    setErrors([]);
    if (step === 0) {
      router.push("/dashboard/locations");
      return;
    }
    setStep((current) => Math.max(0, current - 1));
  };

  const basePayload = () => ({
    name: draft.name.trim(),
    category: draft.category.trim(),
    has_storefront: draft.hasStorefront,
    street: draft.hasStorefront ? draft.street.trim() : null,
    city: draft.hasStorefront ? draft.city.trim() : null,
    state: draft.hasStorefront ? draft.state.trim() || null : null,
    postal_code: draft.postalCode.trim() || null,
    country: draft.country.trim().toUpperCase(),
    phone: draft.phone.trim() || null,
  });

  const runDuplicateCheck = async () => {
    const seq = ++duplicateSeq.current;
    setDuplicateLoading(true);
    setDuplicateError(null);
    setDuplicates(null);
    try {
      const rows = await apiFetch("/api/v1/locations/search", {
        method: "POST",
        body: JSON.stringify(basePayload()),
      });
      if (seq === duplicateSeq.current) {
        setDuplicates(Array.isArray(rows) ? (rows as LocationMatch[]) : []);
      }
    } catch (error) {
      if (seq === duplicateSeq.current) {
        setDuplicateError(
          error instanceof Error ? error.message : "Google could not check for duplicates.",
        );
      }
    } finally {
      if (seq === duplicateSeq.current) setDuplicateLoading(false);
    }
  };

  const createOnGoogle = async () => {
    if (creating || blockedByClaim) return;
    setCreating(true);
    setCreateError(null);
    if (!requestIdRef.current) {
      requestIdRef.current =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `loc-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    }
    try {
      const result = (await apiFetch("/api/v1/locations", {
        method: "POST",
        body: JSON.stringify({
          ...basePayload(),
          latitude: draft.pin?.lat ?? null,
          longitude: draft.pin?.lng ?? null,
          website: draft.website.trim() || null,
          description: draft.description.trim() || null,
          language_code: locale.startsWith("ar") ? "ar" : "en",
          // A storefront that does not deliver must not inherit areas typed
          // before the wizard switched back to "customers can visit".
          service_area:
            !draft.hasStorefront || draft.delivers ? draft.serviceAreas : [],
          request_id: requestIdRef.current,
        }),
      })) as CreatedLocation;
      requestIdRef.current = "";
      setCreated(result);
      try {
        sessionStorage.removeItem(DRAFT_KEY);
      } catch {
        /* private mode */
      }
      setStep(5);
    } catch (error) {
      setCreateError(
        error instanceof Error ? error.message : "Google could not create this location.",
      );
    } finally {
      setCreating(false);
    }
  };

  const addArea = () => {
    const value = areaInput.trim();
    if (!value) return;
    if (draft.serviceAreas.length >= MAX_SERVICE_AREAS) {
      setErrors([`You can add up to ${MAX_SERVICE_AREAS} service areas.`]);
      return;
    }
    if (draft.serviceAreas.some((area) => area.toLowerCase() === value.toLowerCase())) {
      setAreaInput("");
      return;
    }
    update({ serviceAreas: [...draft.serviceAreas, value] });
    setAreaInput("");
    setErrors([]);
  };

  const removeArea = (area: string) => {
    update({ serviceAreas: draft.serviceAreas.filter((item) => item !== area) });
  };

  const blockedByClaim = (duplicates ?? []).some((match) => !!match.request_admin_rights_url);
  const duplicateReady = duplicates !== null || duplicateError !== null;

  if (!hydrated) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <LogoLoader size={30} />
      </div>
    );
  }

  if (connection === "checking") {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <LogoLoader size={30} />
      </div>
    );
  }

  if (connection === "no") {
    return (
      <div className="mx-auto w-full max-w-2xl p-4 sm:p-8">
        <Link href="/dashboard/locations" className="text-[12px] font-semibold text-ink/50 hover:text-ink dark:text-fog/50 dark:hover:text-fog">
          ← Locations
        </Link>
        <div className="mt-5 rounded-2xl border border-ink/[0.06] bg-white p-6 shadow-sm dark:border-fog/[0.08] dark:bg-ink">
          <h1 className="text-[22px] font-bold text-ink dark:text-fog">
            Connect Google Business Profile first
          </h1>
          <p className="mt-2 text-[13px] leading-relaxed text-ink/60 dark:text-fog/60">
            A location is created inside the Google account you connect to Sayvors. Connect the
            owner or manager account, then come back to this page.
          </p>
          <Link href="/dashboard/channels" className="btn-primary mt-5 inline-flex">
            Connect Google
          </Link>
        </div>
      </div>
    );
  }

  const verifyHref = created
    ? `/dashboard/verification?channel=${encodeURIComponent(created.channel_id)}&next=${encodeURIComponent(
        `/dashboard/locations/new/customize?channel=${encodeURIComponent(created.channel_id)}&listing=${encodeURIComponent(created.listing_id)}`,
      )}`
    : "/dashboard/verification";
  const customizeHref = created
    ? `/dashboard/locations/new/customize?channel=${encodeURIComponent(created.channel_id)}&listing=${encodeURIComponent(created.listing_id)}`
    : "/dashboard/locations";

  return (
    <div className="mx-auto w-full max-w-6xl p-3 sm:p-6">
      <div className="grid gap-5 lg:grid-cols-[250px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <Link
            href="/dashboard/locations"
            className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-ink/50 transition hover:text-ink dark:text-fog/50 dark:hover:text-fog"
          >
            ← Locations
          </Link>
          <h1 className="mt-3 text-[22px] font-bold tracking-tight text-ink dark:text-fog">
            Add a location
          </h1>
          <p className="mt-1 text-[12px] leading-relaxed text-ink/50 dark:text-fog/50">
            Build a Google Business Profile that customers can find on Search and Maps.
          </p>

          <ol className="mt-5 space-y-3">
            {STEPS.map((item, index) => {
              const done = index < step;
              const active = index === step;
              return (
                <li key={item.key} className="flex gap-2.5">
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
                      done
                        ? "bg-emerald-500 text-white"
                        : active
                          ? "bg-deep-violet text-white"
                          : "bg-ink/[0.06] text-ink/35 dark:bg-fog/[0.08] dark:text-fog/35"
                    }`}
                  >
                    {done ? "✓" : index + 1}
                  </span>
                  <div className="min-w-0">
                    <p
                      className={`text-[12px] font-semibold ${
                        active
                          ? "text-ink dark:text-fog"
                          : done
                            ? "text-ink/65 dark:text-fog/65"
                            : "text-ink/40 dark:text-fog/40"
                      }`}
                    >
                      {item.label}
                    </p>
                    <p className="text-[10.5px] leading-snug text-ink/35 dark:text-fog/35">
                      {item.hint}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="mt-6 rounded-xl border border-ink/[0.06] bg-white p-3 text-[11px] leading-relaxed text-ink/50 dark:border-fog/[0.08] dark:bg-ink dark:text-fog/50">
            <p className="font-bold text-ink/65 dark:text-fog/65">What happens next</p>
            <p className="mt-1">
              Sayvors checks Google for duplicates, creates the location, then hands you to Google
              verification. Nothing is public until Google verifies it.
            </p>
          </div>
        </aside>

        <main className="min-w-0">
          <div className="rounded-2xl border border-ink/[0.06] bg-white p-5 shadow-sm sm:p-7 dark:border-fog/[0.08] dark:bg-ink">
            <div className="mb-5 flex items-start justify-between gap-3">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-deep-violet">
                  Step {step + 1} of {STEPS.length}
                </p>
                <h2 className="mt-0.5 text-[20px] font-bold tracking-tight text-ink dark:text-fog">
                  {STEPS[step].label}
                </h2>
              </div>
              <button type="button" onClick={goBack} className="btn-secondary shrink-0">
                {step === 0 ? "Cancel" : "Back"}
              </button>
            </div>

            {errors.length > 0 && (
              <p role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-[12px] text-red-700 dark:border-red-500/25 dark:bg-red-500/10 dark:text-red-200">
                Required: {errors.join(", ")}.
              </p>
            )}

            {step === 0 && (
              <div className="space-y-5">
                <div className="relative">
                  <Field
                    label="Business name"
                    required
                    hint="Use the real-world name customers know. You can add branches later."
                  >
                    <input
                      value={draft.name}
                      onChange={(event) => update({ name: event.target.value })}
                      placeholder="Sayvors Company"
                      className="input-field"
                      autoComplete="organization"
                    />
                  </Field>

                  {(matchLoading || matches.length > 0 || matchError) && (
                    <div className="mt-1.5 overflow-hidden rounded-xl border border-ink/[0.08] bg-white shadow-lg dark:border-fog/[0.08] dark:bg-ink">
                      <button
                        type="button"
                        onClick={() => {
                          setMatches([]);
                          setMatchError(null);
                        }}
                        className="flex w-full items-start gap-2 border-b border-ink/[0.06] px-3.5 py-2.5 text-left transition hover:bg-ink/[0.03] dark:border-fog/[0.06] dark:hover:bg-fog/[0.04]"
                      >
                        <span className="mt-0.5 text-[12px] text-deep-violet">＋</span>
                        <span>
                          <span className="block text-[12.5px] font-semibold text-ink dark:text-fog">
                            Create a business with this name
                          </span>
                          <span className="block text-[10.5px] text-ink/40 dark:text-fog/40">
                            {draft.name.trim() || "Start typing a name"}
                          </span>
                        </span>
                      </button>
                      {matchLoading && (
                        <p className="px-3.5 py-2.5 text-[11.5px] text-ink/45 dark:text-fog/45">
                          Checking Google for existing listings...
                        </p>
                      )}
                      {!matchLoading &&
                        matches.map((match, index) => (
                          <div
                            key={`${match.location_name ?? match.name}-${index}`}
                            className="border-b border-ink/[0.05] px-3.5 py-2.5 last:border-b-0 dark:border-fog/[0.05]"
                          >
                            <p className="text-[12.5px] font-semibold text-ink dark:text-fog">
                              {match.name}
                            </p>
                            {match.address && (
                              <p className="mt-0.5 text-[10.5px] leading-relaxed text-ink/45 dark:text-fog/45">
                                {match.address}
                              </p>
                            )}
                            {match.request_admin_rights_url && (
                              <a
                                href={match.request_admin_rights_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="mt-1 inline-flex text-[10.5px] font-bold text-[#1a73e8] hover:underline"
                              >
                                Request access to this listing →
                              </a>
                            )}
                          </div>
                        ))}
                      {matchError && !matchLoading && (
                        <p className="px-3.5 py-2.5 text-[11px] text-amber-700 dark:text-amber-300">
                          Suggestions unavailable: {matchError}
                        </p>
                      )}
                    </div>
                  )}
                </div>

                <div>
                  <p className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.08em] text-ink/55 dark:text-fog/55">
                    Business category *
                  </p>
                  <CategoryPicker
                    value={draft.category}
                    region={draft.country || "SA"}
                    onChange={(category) => update({ category })}
                  />
                </div>
              </div>
            )}

            {step === 1 && (
              <div className="space-y-3">
                <p className="text-[13px] leading-relaxed text-ink/60 dark:text-fog/60">
                  Do you want to add a location customers can visit, like a store or office?
                </p>
                {[
                  {
                    value: true,
                    title: "Yes, customers can visit",
                    body: "Add a street address and a map pin. The location will appear on Google Maps and Search.",
                  },
                  {
                    value: false,
                    title: "No, I serve customers at their location",
                    body: "Add the areas you serve. Google will not show a street address on the profile.",
                  },
                ].map((option) => (
                  <button
                    key={String(option.value)}
                    type="button"
                    aria-pressed={draft.hasStorefront === option.value}
                    onClick={() => update({ hasStorefront: option.value })}
                    className={`flex w-full items-start gap-3 rounded-xl border p-3.5 text-left transition focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 ${
                      draft.hasStorefront === option.value
                        ? "border-deep-violet bg-deep-violet/[0.04] dark:border-deep-violet/50 dark:bg-deep-violet/10"
                        : "border-ink/[0.08] hover:bg-ink/[0.02] dark:border-fog/[0.08] dark:hover:bg-fog/[0.03]"
                    }`}
                  >
                    <span
                      className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
                        draft.hasStorefront === option.value
                          ? "border-deep-violet"
                          : "border-ink/25 dark:border-fog/25"
                      }`}
                    >
                      {draft.hasStorefront === option.value && (
                        <span className="h-2 w-2 rounded-full bg-deep-violet" />
                      )}
                    </span>
                    <span>
                      <span className="block text-[13px] font-semibold text-ink dark:text-fog">
                        {option.title}
                      </span>
                      <span className="mt-0.5 block text-[11.5px] leading-relaxed text-ink/50 dark:text-fog/50">
                        {option.body}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
            )}

            {step === 2 && (
              <div className="space-y-5">
                {draft.hasStorefront ? (
                  <>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field label="Country / region" required>
                        <select
                          value={draft.country}
                          onChange={(event) => update({ country: event.target.value })}
                          className="input-field"
                        >
                          {COUNTRIES.map((country) => (
                            <option key={country.code} value={country.code}>
                              {country.name}
                            </option>
                          ))}
                        </select>
                      </Field>
                      <Field label="State / province" hint="Needed for accurate geocoding in the US, Canada and Australia.">
                        <input
                          value={draft.state}
                          onChange={(event) => update({ state: event.target.value })}
                          placeholder="Riyadh Province"
                          className="input-field"
                        />
                      </Field>
                    </div>
                    <Field label="Street address" required>
                      <input
                        value={draft.street}
                        onChange={(event) => update({ street: event.target.value })}
                        placeholder="Street and number"
                        className="input-field"
                        autoComplete="street-address"
                      />
                    </Field>
                    <div className="grid gap-4 sm:grid-cols-2">
                      <Field label="City" required>
                        <input
                          value={draft.city}
                          onChange={(event) => update({ city: event.target.value })}
                          placeholder="Riyadh"
                          className="input-field"
                          autoComplete="address-level2"
                        />
                      </Field>
                      <Field label="Postal code">
                        <input
                          value={draft.postalCode}
                          onChange={(event) => update({ postalCode: event.target.value })}
                          placeholder="12213"
                          className="input-field"
                          autoComplete="postal-code"
                        />
                      </Field>
                    </div>

                    <div>
                      <p className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.08em] text-ink/55 dark:text-fog/55">
                        Pin the exact location
                      </p>
                      <LocationPinMap
                        apiKey={MAPS_KEY}
                        address={fullAddress}
                        value={draft.pin}
                        onChange={(pin) => update({ pin })}
                      />
                    </div>
                  </>
                ) : (
                  <div className="rounded-xl border border-deep-violet/15 bg-deep-violet/[0.03] p-3.5 text-[12px] leading-relaxed text-ink/60 dark:border-deep-violet/25 dark:bg-deep-violet/10 dark:text-fog/60">
                    Google will not show a street address for this business. Add the cities,
                    districts or postal codes you serve.
                  </div>
                )}

                <div className="rounded-xl border border-ink/[0.06] p-3.5 dark:border-fog/[0.08]">
                  <label className="flex items-start gap-2.5">
                    <input
                      type="checkbox"
                      checked={!draft.hasStorefront || draft.delivers}
                      disabled={!draft.hasStorefront}
                      onChange={(event) =>
                        update({
                          delivers: event.target.checked,
                          serviceAreas: event.target.checked ? draft.serviceAreas : [],
                        })
                      }
                      className="mt-0.5 h-4 w-4 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/40"
                    />
                    <span>
                      <span className="block text-[12.5px] font-semibold text-ink dark:text-fog">
                        I also deliver or visit customers
                      </span>
                      <span className="mt-0.5 block text-[10.5px] text-ink/45 dark:text-fog/45">
                        Add the areas you serve. This is optional for a storefront.
                      </span>
                    </span>
                  </label>

                  {(!draft.hasStorefront || draft.delivers) && (
                    <div className="mt-3">
                      <div className="flex gap-2">
                        <input
                          value={areaInput}
                          onChange={(event) => setAreaInput(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              addArea();
                            }
                          }}
                          placeholder="Search and add an area (e.g. Al Malqa, Riyadh)"
                          className="input-field"
                        />
                        <button type="button" onClick={addArea} className="btn-secondary shrink-0">
                          Add
                        </button>
                      </div>
                      {draft.serviceAreas.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {draft.serviceAreas.map((area) => (
                            <span
                              key={area}
                              className="inline-flex items-center gap-1.5 rounded-full border border-ink/10 bg-ink/[0.03] px-2.5 py-1 text-[11px] font-medium text-ink/70 dark:border-fog/10 dark:bg-fog/[0.05] dark:text-fog/70"
                            >
                              {area}
                              <button
                                type="button"
                                onClick={() => removeArea(area)}
                                aria-label={`Remove ${area}`}
                                className="text-ink/35 hover:text-red-600 dark:text-fog/35"
                              >
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      )}
                      <p className="mt-1.5 text-[10.5px] text-ink/40 dark:text-fog/40">
                        We match these names to Google service areas. Up to {MAX_SERVICE_AREAS}.
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="space-y-5">
                <Field
                  label="Phone number"
                  required
                  hint="Include the country code, for example +966 55 000 0000."
                >
                  <input
                    value={draft.phone}
                    onChange={(event) => update({ phone: event.target.value })}
                    placeholder="+966 55 000 0000"
                    className="input-field"
                    autoComplete="tel"
                    inputMode="tel"
                  />
                </Field>
                <Field label="Website" hint="Optional. Use the page for this location if one exists.">
                  <input
                    value={draft.website}
                    onChange={(event) => update({ website: event.target.value })}
                    placeholder="https://..."
                    className="input-field"
                    autoComplete="url"
                    inputMode="url"
                  />
                </Field>
                <Field
                  label="Business description"
                  hint="Up to 750 characters. Google recommends a description for every non-lodging category; you can edit it later."
                >
                  <textarea
                    value={draft.description}
                    onChange={(event) => update({ description: event.target.value.slice(0, 750) })}
                    rows={5}
                    placeholder="Tell customers what you do and what makes your business different."
                    className="input-field resize-y"
                  />
                  <span className="mt-1 block text-right text-[10.5px] text-ink/35 dark:text-fog/35">
                    {draft.description.length}/750
                  </span>
                </Field>
                <p className="text-[11px] leading-relaxed text-ink/40 dark:text-fog/40">
                  Google chat/messaging is managed inside Google Business Profile. Sayvors does not
                  create a messaging number for you.
                </p>
              </div>
            )}

            {step === 4 && (
              <div className="space-y-5">
                <dl className="grid gap-2 rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4 text-[12px] dark:border-fog/[0.08] dark:bg-fog/[0.03] sm:grid-cols-2">
                  {[
                    ["Business name", draft.name || "-"],
                    ["Category", draft.category || "-"],
                    [
                      "Location",
                      draft.hasStorefront
                        ? [draft.street, draft.city, draft.state, draft.postalCode, countryName]
                            .filter(Boolean)
                            .join(", ") || "-"
                        : "Service area business",
                    ],
                    ["Phone", draft.phone || "-"],
                    ["Website", draft.website || "-"],
                    [
                      "Service areas",
                      (!draft.hasStorefront || draft.delivers) && draft.serviceAreas.length
                        ? draft.serviceAreas.join(", ")
                        : "None",
                    ],
                    ["Description", draft.description || "Not added"],
                    [
                      "Map pin",
                      draft.pin
                        ? `${draft.pin.lat.toFixed(5)}, ${draft.pin.lng.toFixed(5)}`
                        : "Google will geocode the address",
                    ],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <dt className="text-[10px] font-bold uppercase tracking-[0.08em] text-ink/40 dark:text-fog/40">
                        {label}
                      </dt>
                      <dd className="mt-0.5 break-words font-semibold text-ink dark:text-fog">
                        {value}
                      </dd>
                    </div>
                  ))}
                </dl>

                <div className="rounded-xl border border-ink/[0.06] p-3.5 dark:border-fog/[0.08]">
                  <p className="text-[12px] font-bold text-ink dark:text-fog">
                    Duplicate check
                  </p>
                  {duplicateLoading && (
                    <p className="mt-1 text-[11.5px] text-ink/50 dark:text-fog/50">
                      Checking Google for existing or claimed listings...
                    </p>
                  )}
                  {!duplicateLoading && duplicateError && (
                    <div className="mt-1.5 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-[11.5px] text-amber-800 dark:border-amber-500/25 dark:bg-amber-500/10 dark:text-amber-200">
                      <p>{duplicateError}</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => void runDuplicateCheck()}
                          className="rounded-lg bg-amber-600 px-2.5 py-1 text-[10.5px] font-bold text-white"
                        >
                          Retry check
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setDuplicateError(null);
                            setDuplicates([]);
                          }}
                          className="rounded-lg border border-amber-300 px-2.5 py-1 text-[10.5px] font-bold text-amber-800 dark:border-amber-500/30 dark:text-amber-200"
                        >
                          Create anyway
                        </button>
                      </div>
                    </div>
                  )}
                  {!duplicateLoading && duplicates && duplicates.length === 0 && (
                    <p className="mt-1 text-[11.5px] text-emerald-700 dark:text-emerald-300">
                      No existing Google listing matched this business. You can create it.
                    </p>
                  )}
                  {!duplicateLoading && duplicates && duplicates.length > 0 && (
                    <div className="mt-1.5 space-y-2">
                      <p className="text-[11.5px] text-amber-800 dark:text-amber-200">
                        Google found {duplicates.length} possible match
                        {duplicates.length === 1 ? "" : "es"}. If one is yours, request access
                        instead of creating a duplicate.
                      </p>
                      {blockedByClaim && (
                        <p className="rounded-lg border border-red-200 bg-red-50 p-2.5 text-[11px] font-semibold text-red-700 dark:border-red-500/25 dark:bg-red-500/10 dark:text-red-200">
                          At least one match is already claimed. Use “Request access” on that
                          listing; creating another listing would duplicate it.
                        </p>
                      )}
                      <ul className="space-y-2">
                        {duplicates.map((match, index) => (
                          <li
                            key={`${match.location_name ?? match.name}-${index}`}
                            className="rounded-lg border border-ink/[0.06] p-2.5 dark:border-fog/[0.08]"
                          >
                            <p className="text-[12px] font-semibold text-ink dark:text-fog">
                              {match.name}
                            </p>
                            {match.address && (
                              <p className="mt-0.5 text-[10.5px] text-ink/45 dark:text-fog/45">
                                {match.address}
                              </p>
                            )}
                            {match.request_admin_rights_url && (
                              <a
                                href={match.request_admin_rights_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="mt-1 inline-flex text-[10.5px] font-bold text-[#1a73e8] hover:underline"
                              >
                                Request access →
                              </a>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {createError && (
                  <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-[12px] text-red-700 dark:border-red-500/25 dark:bg-red-500/10 dark:text-red-200">
                    {createError}
                  </p>
                )}

                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() => void createOnGoogle()}
                    disabled={
                      creating ||
                      duplicateLoading ||
                      blockedByClaim ||
                      !duplicateReady
                    }
                    className="btn-primary disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {creating ? "Creating on Google..." : "Create on Google"}
                  </button>
                  <button type="button" onClick={goBack} className="btn-secondary" disabled={creating}>
                    Back
                  </button>
                </div>
              </div>
            )}

            {step === 5 && created && (
              <div className="space-y-5">
                <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-500/25 dark:bg-emerald-500/10">
                  <p className="text-[13px] font-bold text-emerald-900 dark:text-emerald-100">
                    {created.created ? "Location created on Google" : "Location linked to Sayvors"}
                  </p>
                  <p className="mt-1 text-[12.5px] font-semibold text-emerald-800 dark:text-emerald-200">
                    {created.name}
                  </p>
                  {created.address && (
                    <p className="mt-0.5 text-[11px] leading-relaxed text-emerald-700/80 dark:text-emerald-200/70">
                      {created.address}
                    </p>
                  )}
                </div>
                <p className="text-[12.5px] leading-relaxed text-ink/60 dark:text-fog/60">
                  New locations stay invisible on Maps and Search until Google verifies them. Open
                  verification, choose the method Google offers, and complete it. You can customize
                  hours, description and photos now; the edits become visible after verification.
                </p>
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Link href={verifyHref} className="btn-primary flex flex-1 items-center justify-center">
                    Verify with Google
                  </Link>
                  <Link href={customizeHref} className="btn-secondary flex flex-1 items-center justify-center">
                    Customize profile
                  </Link>
                </div>
                <Link
                  href="/dashboard/locations"
                  className="inline-flex text-[12px] font-semibold text-ink/50 underline underline-offset-2 hover:text-ink dark:text-fog/50 dark:hover:text-fog"
                >
                  Back to locations
                </Link>
              </div>
            )}

            {step < 4 && (
              <div className="mt-6 flex flex-wrap items-center justify-between gap-2 border-t border-ink/[0.06] pt-4 dark:border-fog/[0.08]">
                <button type="button" onClick={goBack} className="btn-secondary">
                  {step === 0 ? "Cancel" : "Back"}
                </button>
                <button type="button" onClick={goNext} className="btn-primary">
                  Continue
                </button>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
