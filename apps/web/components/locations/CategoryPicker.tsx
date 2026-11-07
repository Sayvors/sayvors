"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch } from "@/lib/api-rag";

interface Category {
  name: string;
  display_name: string;
}

/**
 * Popular groups are a navigation aid, not a category source. Every name is
 * validated against Google's catalog before it is accepted, so a renamed or
 * removed category fails here with a clear message instead of at create.
 */
const POPULAR_GROUPS: { label: string; categories: string[] }[] = [
  {
    label: "Food & drink",
    categories: ["Restaurant", "Cafe", "Coffee shop", "Bakery", "Bar", "Ice cream shop"],
  },
  {
    label: "Shopping",
    categories: [
      "Clothing store",
      "Shoe store",
      "Jewelry store",
      "Electronics store",
      "Furniture store",
      "Gift shop",
    ],
  },
  {
    label: "Services",
    categories: [
      "Hair salon",
      "Beauty salon",
      "Nail salon",
      "Spa",
      "Dentist",
      "Doctor",
      "Lawyer",
      "Accountant",
      "Real estate agency",
      "Marketing agency",
      "Software company",
    ],
  },
  {
    label: "Hotels & lodging",
    categories: ["Hotel", "Motel", "Bed & breakfast", "Guest house"],
  },
  {
    label: "Outdoors & recreation",
    categories: ["Gym", "Yoga studio", "Park", "Tourist attraction"],
  },
  { label: "Religion", categories: ["Mosque", "Church"] },
  { label: "Office & industrial", categories: ["Corporate office", "Warehouse", "Factory"] },
  { label: "Residential", categories: ["Apartment building", "Condominium complex"] },
  { label: "Education", categories: ["School", "Driving school", "Tutoring service"] },
];

export default function CategoryPicker({
  value,
  region,
  onChange,
  showSelected = true,
  showPopular = true,
  placeholder = "Search Google categories...",
}: {
  value: string;
  region: string;
  onChange: (displayName: string) => void;
  showSelected?: boolean;
  showPopular?: boolean;
  placeholder?: string;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Category[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openGroup, setOpenGroup] = useState<string | null>(null);
  const requestSeq = useRef(0);

  const search = useCallback(
    async (text: string) => {
      const token = ++requestSeq.current;
      setLoading(true);
      setError(null);
      try {
        const rows = (await apiFetch(
          `/api/v1/locations/categories?q=${encodeURIComponent(text)}&region=${encodeURIComponent(region)}`,
        )) as Category[];
        if (token === requestSeq.current) {
          setResults(Array.isArray(rows) ? rows : []);
        }
      } catch (e) {
        if (token === requestSeq.current) {
          setResults([]);
          setError(e instanceof Error ? e.message : "Google categories could not load.");
        }
      } finally {
        if (token === requestSeq.current) setLoading(false);
      }
    },
    [region],
  );

  useEffect(() => {
    const text = query.trim();
    if (!text) {
      setResults([]);
      setError(null);
      return;
    }
    const timer = setTimeout(() => void search(text), 350);
    return () => clearTimeout(timer);
  }, [query, search]);

  const choose = useCallback(
    async (displayName: string) => {
      setLoading(true);
      setError(null);
      try {
        const rows = (await apiFetch(
          `/api/v1/locations/categories?q=${encodeURIComponent(displayName)}&region=${encodeURIComponent(region)}&exact=1`,
        )) as Category[];
        const match = (Array.isArray(rows) ? rows : []).find(
          (item) => item.display_name.trim().toLowerCase() === displayName.trim().toLowerCase(),
        );
        if (!match) {
          setError(
            `Google does not list “${displayName}” as a category right now. Search for it instead.`,
          );
          return;
        }
        onChange(match.display_name);
        setQuery("");
        setResults([]);
        setOpenGroup(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Google categories could not load.");
      } finally {
        setLoading(false);
      }
    },
    [onChange, region],
  );

  if (!region || region.trim().length !== 2) {
    return (
      <p className="rounded-xl border border-dashed border-ink/15 bg-ink/[0.02] p-3 text-[12px] leading-relaxed text-ink/55 dark:border-fog/15 dark:bg-fog/[0.02] dark:text-fog/55">
        Choose the business country first. Google&apos;s category list is
        region-specific.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {showSelected && value && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 dark:border-emerald-500/25 dark:bg-emerald-500/10">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-[0.08em] text-emerald-700 dark:text-emerald-300">
              Primary category
            </p>
            <p className="truncate text-[13px] font-semibold text-emerald-900 dark:text-emerald-100">
              {value}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onChange("")}
            className="shrink-0 rounded-lg px-2 py-1 text-[11px] font-bold text-emerald-700 underline underline-offset-2 hover:bg-emerald-100 dark:text-emerald-300 dark:hover:bg-emerald-500/10"
          >
            Change
          </button>
        </div>
      )}

      <div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholder}
          className="input-field"
          aria-label="Search business categories"
        />
        <p className="mt-1.5 text-[10.5px] text-ink/40 dark:text-fog/40">
          Categories come from Google. You can change the primary category later.
        </p>
      </div>

      {error && (
        <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800 dark:border-amber-500/25 dark:bg-amber-500/10 dark:text-amber-200">
          {error}
        </p>
      )}

      {query.trim() && (
        <div className="overflow-hidden rounded-xl border border-ink/[0.08] dark:border-fog/[0.08]">
          {loading && (
            <p className="p-3 text-[12px] text-ink/45 dark:text-fog/45">Searching Google...</p>
          )}
          {!loading && results.length === 0 && !error && (
            <p className="p-3 text-[12px] text-ink/45 dark:text-fog/45">
              No matching category. Try a shorter, more general name.
            </p>
          )}
          {!loading &&
            results.map((category) => (
              <button
                key={category.name}
                type="button"
                onClick={() => void choose(category.display_name)}
                className="flex w-full items-center justify-between gap-3 border-b border-ink/[0.05] px-3.5 py-2.5 text-left transition last:border-b-0 hover:bg-ink/[0.03] dark:border-fog/[0.05] dark:hover:bg-fog/[0.04]"
              >
                <span className="text-[12.5px] font-medium text-ink dark:text-fog">
                  {category.display_name}
                </span>
                <span className="text-[10px] text-ink/30 dark:text-fog/30">Select</span>
              </button>
            ))}
        </div>
      )}

      {showPopular && !query.trim() && (
        <div className="overflow-hidden rounded-xl border border-ink/[0.08] dark:border-fog/[0.08]">
          <p className="border-b border-ink/[0.06] bg-ink/[0.02] px-3.5 py-2 text-[10px] font-bold uppercase tracking-[0.1em] text-ink/45 dark:border-fog/[0.06] dark:bg-fog/[0.03] dark:text-fog/45">
            Browse popular categories
          </p>
          {POPULAR_GROUPS.map((group) => {
            const open = openGroup === group.label;
            return (
              <div key={group.label} className="border-b border-ink/[0.05] last:border-b-0 dark:border-fog/[0.05]">
                <button
                  type="button"
                  aria-expanded={open}
                  onClick={() => setOpenGroup(open ? null : group.label)}
                  className="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.04]"
                >
                  <span className="text-[12.5px] font-semibold text-ink dark:text-fog">
                    {group.label}
                  </span>
                  <span
                    aria-hidden
                    className={`text-[11px] text-ink/35 transition dark:text-fog/35 ${open ? "rotate-90" : ""}`}
                  >
                    ›
                  </span>
                </button>
                {open && (
                  <div className="grid gap-1 bg-ink/[0.015] px-2 pb-2 pt-1 dark:bg-fog/[0.02]">
                    {group.categories.map((name) => (
                      <button
                        key={name}
                        type="button"
                        disabled={loading}
                        onClick={() => void choose(name)}
                        className="rounded-lg px-2.5 py-1.5 text-left text-[12px] text-ink/70 transition hover:bg-white hover:text-deep-violet disabled:opacity-50 dark:text-fog/70 dark:hover:bg-ink dark:hover:text-fog"
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
