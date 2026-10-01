"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api-rag";
import LogoLoader from "@/components/LogoLoader";
import { useI18n } from "@/lib/i18n/I18nProvider";

/* ---------------------------------------------------------------------------------------*/

interface Location {
  id: string;
  name: string;
  address: string;
  phone: string;
  website: string;
  status: string;
  categories: string[];
  primary_category: string;
  description: string;
  regular_hours: Record<string, string>;
  special_hours: Record<string, string>;
  service_area: string[];
  attributes: Record<string, string>;
  permanently_closed: boolean;
}

interface LocationOption {
  id: string;
  name: string;
  address: string;
  status: string;
}

interface LocationGroup {
  id: string;
  name: string;
  listing_ids: string[];
  position: number;
}

interface LocalithConn {
  listing_id: string;
  listing_name: string;
  address?: string | null;
  phone_number?: string | null;
  website_url?: string | null;
  maps_url?: string | null;
  is_verified?: boolean | null;
  is_suspended?: boolean | null;
  total_reviews?: number;
  average_rating?: number;
}

/* ── Bulk edit: "All branches" scope. Tabs stay untouched in shape —
   they receive an optional `bulk` prop (branch count + per-field
   "varies" set) and blank initials; saving fans out per branch. -- */

const ALL = "__all__";
/* Groups ride in the same <select> as single locations and "All branches".
   A group value is prefixed so it can never collide with a listing ID. */
const GROUP_PREFIX = "__group__:";
const groupValue = (id: string) => `${GROUP_PREFIX}${id}`;
const parseGroupValue = (v: string) => (v.startsWith(GROUP_PREFIX) ? v.slice(GROUP_PREFIX.length) : null);

interface BulkScope {
  branches: { id: string; name: string }[];
  varies: Set<string>;
  /**
   * Per-branch current value for the fields that live on the Google-synced
   * connection row (phone / website). In "All branches" mode there is no single
   * profile to prefill from, so the inputs start blank — without this the
   * merchant sees empty fields next to a filled-in "varies" badge and cannot
   * tell what each branch actually holds.
   */
  fieldValues?: Record<string, Record<string, string>>;
}

interface BulkFailed {
  id: string;
  name: string;
  error: string;
}

interface FullProfile {
  listing_id: string;
  name: string;
  address?: string | null;
  phone?: string | null;
  website?: string | null;
  maps_url?: string | null;
  status: string;
  is_verified?: boolean | null;
  description?: string | null;
  categories: { primary?: string; additional?: string[] };
  hours: { regular?: Record<string, { open: string; close: string; closed: boolean }>; special?: { date: string; hours: string; reason: string }[]; more?: { type: string; open: string; close: string }[] };
  service_area: string[];
  attributes: Record<string, string>;
  opening_date?: string | null;
  google_synced: string[];
  updated_at?: string | null;
}

function SourceBadge({ google, copy }: { google: boolean; copy: LocationsCopy }) {
  return google ? (
    <span className="whitespace-nowrap rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
      {copy.syncedToGoogle}
    </span>
  ) : (
    <span className="whitespace-nowrap rounded-full bg-ink/[0.05] px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink/45 dark:bg-fog/[0.06] dark:text-fog/45">
      {copy.storedInSayvors}
    </span>
  );
}

function CompletenessCard({
  profile,
  fullProfile,
  copy,
}: {
  profile: LocalithConn;
  fullProfile?: FullProfile | null;
  copy: LocationsCopy;
}) {
  const displayName = fullProfile?.name ?? profile.listing_name;
  const essentials: { label: string; done: boolean; hint?: string }[] = [
    { label: copy.essentialName, done: !!displayName },
    { label: copy.essentialAddress, done: !!profile.address },
    { label: copy.essentialWebsite, done: !!profile.website_url },
    { label: copy.essentialPhone, done: !!profile.phone_number, hint: !profile.phone_number ? copy.addPhone : undefined },
  ];
  const done = essentials.filter((e) => e.done).length;
  if (done >= essentials.length) return null;
  return (
    <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[14px] font-bold text-ink dark:text-fog">{copy.completeness}</h2>
        <p className="text-[11px] font-semibold text-ink/45 dark:text-fog/45">
          {copy.essentialsDone
            .replace("{done}", String(done))
            .replace("{total}", String(essentials.length))}
        </p>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/[0.06] dark:bg-fog/[0.06]">
        <div className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all" style={{ width: `${(done / essentials.length) * 100}%` }} />
      </div>
      <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
        {essentials.map((e) => (
          <li key={e.label} className="flex items-center gap-2 text-[12px]">
            <span className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold ${e.done ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
              {e.done ? "✓" : "•"}
            </span>
            <span className="font-medium text-ink/70 dark:text-fog/70">{e.label}</span>
            {e.hint && <span className="text-[11px] font-semibold text-amber-600">· {e.hint}</span>}
          </li>
        ))}
      </ul>
      <p className="mt-3 border-t border-ink/[0.05] pt-2 text-[11px] text-ink/40 dark:text-fog/40">
        ★ {(profile.average_rating ?? 0).toFixed(1)} · {profile.total_reviews ?? 0}{" "}
        {copy.reviewsLabel} · {copy.completenessFootnote}
      </p>
    </div>
  );
}

// English day names are the wire format: the API matches them case-insensitively
// against MONDAY..SUNDAY, so they must stay English as object keys. Only the
// visible label is localised, via DAY_LABEL_KEYS.
const HOURS_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

const DAY_LABEL_KEYS = {
  Monday: "dayMonday",
  Tuesday: "dayTuesday",
  Wednesday: "dayWednesday",
  Thursday: "dayThursday",
  Friday: "dayFriday",
  Saturday: "daySaturday",
  Sunday: "daySunday",
} as const;

const dayLabel = (day: string, copy: LocationsCopy): string => {
  const key = DAY_LABEL_KEYS[day as keyof typeof DAY_LABEL_KEYS];
  return key ? copy[key] : day;
};

type LocationsCopy = ReturnType<typeof useI18n>["t"]["analytics"]["locations"];

/** Location status arrives from the API as an English slug → label it. */
function statusLabel(status: string | null | undefined, copy: LocationsCopy): string {
  if (status === "active") return copy.statusActive;
  if (status === "inactive") return copy.statusInactive;
  return copy.statusUnknown;
}

/* ── Page ───────────────────────────────────────── */

export default function LocationsPage() {
  const { t } = useI18n();
  const copy = t.analytics.locations;
  const [loading, setLoading] = useState(true);
  const [locations, setLocations] = useState<LocationOption[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>("details");
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [localith, setLocalith] = useState<LocalithConn | null>(null);
  const [localithConns, setLocalithConns] = useState<Record<string, LocalithConn>>({});
  const [fullProfile, setFullProfile] = useState<FullProfile | null>(null);
  const [bulkProfiles, setBulkProfiles] = useState<Record<string, FullProfile>>({});
  const [createOpen, setCreateOpen] = useState(false);
  const [confirmBulk, setConfirmBulk] = useState<null | {
    title: string;
    lines: string[];
    branches: { id: string; name: string }[];
    busy: boolean;
    onConfirm: () => void;
  }>(null);
  const [lastBulkFail, setLastBulkFail] = useState<null | {
    label: string;
    failed: BulkFailed[];
    onRetry: () => void;
  }>(null);
  const [groups, setGroups] = useState<LocationGroup[]>([]);
  const [groupsOpen, setGroupsOpen] = useState(false);

  const selectedGroupId = selectedId ? parseGroupValue(selectedId) : null;
  const selectedGroup = selectedGroupId
    ? groups.find((g) => g.id === selectedGroupId) ?? null
    : null;
  const isBulk = selectedId === ALL || selectedGroup !== null;
  /* A group narrows the bulk scope to its own members. Locations the group
     references but that are no longer connected are dropped rather than
     shown as permanently failing. Memoised because the bulk-profile effect
     keys on it — a fresh array each render would refetch on every keystroke. */
  const bulkBranches = useMemo(
    () =>
      isBulk
        ? (selectedGroup
            ? locations
                .filter((l) => selectedGroup.listing_ids.includes(l.id))
                .map((l) => ({ id: l.id, name: l.name }))
            : locations.map((l) => ({ id: l.id, name: l.name })))
        : [],
    [isBulk, selectedGroup, locations],
  );

  const showBanner = (kind: "ok" | "err", text: string) => setBanner({ kind, text });

  const saveProfile = async (patch: Record<string, unknown>, okText: string) => {
    if (!selectedId) return;
    try {
      const updated = await apiFetch(`/api/v1/locations/${selectedId}`, {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      setFullProfile(updated as FullProfile);
      const synced = (updated as FullProfile)?.google_synced ?? [];
      showBanner("ok", synced.length > 0 ? `${okText} · Synced to Google (${synced.join(", ")}).` : okText);
    } catch (e) {
      showBanner("err", e instanceof Error ? e.message.slice(0, 160) : "Could not save.");
    }
  };

  // -- Bulk fan-out: same patch → every branch, per-branch results --
  const runBulkProfile = async (
    label: string,
    patch: Record<string, unknown>,
    ids?: string[],
  ): Promise<{ ok: number; failed: BulkFailed[] }> => {
    const targets = (ids ?? bulkBranches.map((b) => b.id)).map((id) => ({
      id,
      name: locations.find((l) => l.id === id)?.name ?? id,
    }));
    const failed: BulkFailed[] = [];
    let ok = 0;
    await Promise.all(
      targets.map(async (t) => {
        try {
          await apiFetch(`/api/v1/locations/${t.id}`, {
            method: "PUT",
            body: JSON.stringify(patch),
          });
          ok++;
        } catch (e) {
          failed.push({
            id: t.id,
            name: t.name,
            error: e instanceof Error ? e.message.slice(0, 120) : "Failed",
          });
        }
      })
    );
    // Refresh the visible profiles.
    try {
      const fresh: Record<string, FullProfile> = {};
      await Promise.all(
        targets.map(async (t) => {
          try {
            fresh[t.id] = (await apiFetch(`/api/v1/locations/${t.id}`)) as FullProfile;
          } catch {
            /* keep stale */
          }
        })
      );
      setBulkProfiles((prev) => ({ ...prev, ...fresh }));
      if (!isBulk && selectedId && fresh[selectedId]) setFullProfile(fresh[selectedId]);
    } catch {
      /* non-fatal */
    }
    const total = targets.length;
    if (failed.length === 0) {
      showBanner("ok", `${label} saved to all ${total} branch${total === 1 ? "" : "es"}.`);
    } else {
      showBanner(
        "err",
        `${label} saved to ${ok} of ${total} — failed: ${failed.map((f) => f.name).join(", ")}.`
      );
    }
    return { ok, failed };
  };

  const runBulkDetails = async (
    data: { phone?: string; website?: string },
    ids?: string[],
  ): Promise<{ ok: number; failed: BulkFailed[] }> => {
    const targets = (ids ?? bulkBranches.map((b) => b.id)).map((id) => ({
      id,
      name: locations.find((l) => l.id === id)?.name ?? id,
    }));
    const failed: BulkFailed[] = [];
    let ok = 0;
    await Promise.all(
      targets.map(async (t) => {
        try {
          await apiFetch(
            `/api/v1/integrations/localith/listing?listing_id=${encodeURIComponent(t.id)}`,
            {
              method: "PATCH",
              body: JSON.stringify({
                ...(data.phone !== undefined ? { phone_number: data.phone || undefined } : {}),
                ...(data.website !== undefined ? { website_url: data.website || undefined } : {}),
              }),
            }
          );
          ok++;
        } catch (e) {
          failed.push({
            id: t.id,
            name: t.name,
            error: e instanceof Error ? e.message.slice(0, 120) : "Failed",
          });
        }
      })
    );
    try {
      const data = await apiFetch("/api/v1/integrations/localith/connections");
      const byId: Record<string, LocalithConn> = {};
      for (const c of (data ?? []) as LocalithConn[]) byId[c.listing_id] = c;
      setLocalithConns(byId);
    } catch {
      /* non-fatal */
    }
    const total = targets.length;
    if (failed.length === 0) {
      showBanner("ok", `Details saved to all ${total} branch${total === 1 ? "" : "es"}.`);
    } else {
      showBanner(
        "err",
        `Details saved to ${ok} of ${total} — failed: ${failed.map((f) => f.name).join(", ")}.`
      );
    }
    return { ok, failed };
  };

  // Bulk entry point for LocationProfile tabs: opens the confirm sheet,
  // then fans the patch out to every branch on confirm.
  const bulkSaveProfile = (
    tabLabel: string,
    patch: Record<string, unknown>,
    lines: string[],
  ) => {
    if (!bulk) return Promise.resolve();
    requestBulkSave(
      `Apply ${tabLabel} to all branches?`,
      lines,
      () => runBulkProfile(tabLabel, patch),
      tabLabel,
      (ids) => runBulkProfile(tabLabel, patch, ids),
    );
    return Promise.resolve();
  };

  // After any fan-out: keep a retry handle while failures remain.
  const finishBulkRun = (
    retryLabel: string,
    retryRun: (ids: string[]) => Promise<{ ok: number; failed: BulkFailed[] }>,
    failed: BulkFailed[],
  ) => {
    if (failed.length === 0) {
      setLastBulkFail(null);
      return;
    }
    setLastBulkFail({
      label: retryLabel,
      failed,
      onRetry: () => {
        setLastBulkFail(null);
        void retryRun(failed.map((f) => f.id)).then(({ failed: still }) =>
          finishBulkRun(retryLabel, retryRun, still)
        );
      },
    });
  };

  // Open the bulk confirm sheet; the fan-out runs only on confirm.
  const requestBulkSave = (
    title: string,
    lines: string[],
    run: () => Promise<{ ok: number; failed: BulkFailed[] }>,
    retryLabel: string,
    retryRun: (ids: string[]) => Promise<{ ok: number; failed: BulkFailed[] }>,
  ) => {
    setLastBulkFail(null);
    setConfirmBulk({
      title,
      lines,
      branches: bulkBranches,
      busy: false,
      onConfirm: () => {
        setConfirmBulk((prev) => (prev ? { ...prev, busy: true } : prev));
        void run().then(({ failed }) => {
          setConfirmBulk(null);
          finishBulkRun(retryLabel, retryRun, failed);
        });
      },
    });
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Localith snapshots first — they carry the real address/phone/website.
        // Every connected branch is listed; nothing is hidden or overwritten.
        try {
          const conns = (await apiFetch("/api/v1/integrations/localith/connections")) as LocalithConn[];
          if (!cancelled && Array.isArray(conns) && conns.length > 0) {
            const byId: Record<string, LocalithConn> = {};
            const opts = conns.map((c) => {
              byId[c.listing_id] = c;
              return {
                id: c.listing_id,
                name: c.listing_name,
                address: c.address ?? "",
                status: c.is_suspended ? "suspended" : c.is_verified ? "active" : "pending",
              };
            });
            setLocalithConns(byId);
            setLocalith(byId[opts[0].id] ?? null);
            setLocations(opts);
            setSelectedId(opts[0].id);
            return;
          }
        } catch {
          /* no Localith connections — fall through to channels */
        }
        try {
          const data = await apiFetch("/api/v1/channels/?limit=100");
          const googleChannels = (data.channels ?? [])
            .filter((channel: { platform: string }) => channel.platform === "google_reviews")
            .map((channel: { id: string; display_name: string | null; status: string }) => ({
              id: channel.id,
              name: channel.display_name ?? "",
              address: "",
              status: channel.status,
            }));
          if (!cancelled) {
            setLocations(googleChannels);
            if (googleChannels.length) setSelectedId(googleChannels[0].id);
          }
        } catch {
          setLocations([]);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

   const selectedLocation = isBulk ? null : (locations.find((l) => l.id === selectedId) ?? locations[0] ?? null);

   // Keep the displayed Localith snapshot scoped to the selected branch.
   useEffect(() => {
     if (!selectedId || isBulk) return;
     setLocalith((prev) => {
       const next = localithConns[selectedId] ?? null;
       return prev?.listing_id === next?.listing_id ? prev : next;
     });
   }, [selectedId, localithConns, isBulk]);

   // Bulk mode: load every branch profile in scope for "varies" comparison.
   useEffect(() => {
     const scope = bulkBranches;
     if (!isBulk || scope.length === 0) {
       setBulkProfiles({});
       return;
     }
     let cancelled = false;
     (async () => {
       const entries = await Promise.all(
         scope.map(async (l) => {
           try {
             const data = await apiFetch(`/api/v1/locations/${l.id}`);
             return [l.id, data as FullProfile] as const;

           } catch {
             return null;
           }
         })
       );
       if (!cancelled) {
         const map: Record<string, FullProfile> = {};
         for (const e of entries) if (e) map[e[0]] = e[1];
         setBulkProfiles(map);
       }
     })();
     return () => { cancelled = true; };
    }, [isBulk, bulkBranches]);

   // Per-field "varies across branches" set for bulk mode.
   const bulkVaries = useMemo(() => {
     const set = new Set<string>();
     if (!isBulk || bulkBranches.length < 2) return set;
     const ids = bulkBranches.map((b) => b.id);
     const differs = (fn: (id: string) => unknown) => {
       const vals = ids.map((id) => JSON.stringify(fn(id) ?? null));
       return new Set(vals).size > 1;
     };
     if (differs((id) => localithConns[id]?.phone_number || "")) set.add("phone");
     if (differs((id) => localithConns[id]?.website_url || "")) set.add("website");
     if (differs((id) => bulkProfiles[id]?.categories?.primary || "")) set.add("primary");
     if (differs((id) => bulkProfiles[id]?.categories?.additional ?? [])) set.add("additional");
     if (differs((id) => bulkProfiles[id]?.hours?.regular ?? {})) set.add("hours");
     if (differs((id) => bulkProfiles[id]?.hours?.special ?? [])) set.add("special");
     if (differs((id) => bulkProfiles[id]?.hours?.more ?? [])) set.add("more");
     if (differs((id) => bulkProfiles[id]?.service_area ?? [])) set.add("service_area");
     if (differs((id) => bulkProfiles[id]?.attributes ?? {})) set.add("attributes");
     if (differs((id) => bulkProfiles[id]?.description || "")) set.add("description");
     return set;
    }, [isBulk, bulkBranches, localithConns, bulkProfiles]);

const bulk: BulkScope | null = isBulk
      ? {
          branches: bulkBranches,
          varies: bulkVaries,
          fieldValues: Object.fromEntries(
            ["phone", "website"].map((f) => [
              f,
              Object.fromEntries(
                bulkBranches.map((l) => {
                  const c = localithConns[l.id];
                  const v = f === "phone" ? c?.phone_number : c?.website_url;
                  return [l.id, (v ?? "").trim()];
                })
              ),
            ])
          ),
        }
      : null;


   // Bulk mode has no single profile — leave the updates tab behind too.
   useEffect(() => {
     if (isBulk && activeTab === "google-updates") setActiveTab("details");
   }, [isBulk, activeTab]);

   // Load the merged profile (Google snapshot + Sayvors store) per location.
   // Bulk mode has no single profile — tabs use blank templates instead.
   useEffect(() => {
     if (!selectedId || isBulk) {
       setFullProfile(null);
       return;
     }
     let cancelled = false;
     (async () => {
       try {
         const data = await apiFetch(`/api/v1/locations/${selectedId}`);
         if (!cancelled) setFullProfile(data as FullProfile);
       } catch {
         if (!cancelled) setFullProfile(null);
       }
     })();
     return () => { cancelled = true; };
   }, [selectedId]);

    // Use fullProfile.name (actual business name) over localith.listing_name when available.
    useEffect(() => {
      const name = fullProfile?.name?.trim();
      if (!name || !selectedId) return;
      setLocations((prev) =>
        prev.map((l) => (l.id === selectedId ? { ...l, name } : l))
      );
    }, [fullProfile, selectedId]);


   const tabs = [
    { key: "details", label: copy.tabDetails },
    { key: "categories", label: copy.tabCategories },
    { key: "hours", label: copy.tabHours },
    { key: "special-hours", label: copy.tabSpecialHours },
    { key: "more-hours", label: copy.tabMoreHours },
    { key: "service-area", label: copy.tabServiceArea },
    { key: "attributes", label: copy.tabAttributes },
    { key: "description", label: copy.tabDescription },
    { key: "google-updates", label: copy.tabGoogleUpdates },
  ];

  // Groups are shared across pages, so fetch once on mount and refresh from
  // the modal. A failure here must not block the page — groups are optional.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiFetch("/api/v1/locations/groups");
        if (!cancelled && Array.isArray(data)) setGroups(data as LocationGroup[]);
      } catch {
        /* groups unavailable — the dropdown just won't list any */
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Deep links: /dashboard/locations?tab=hours etc.
  useEffect(() => {
    try {
      const tab = new URLSearchParams(window.location.search).get("tab");
      if (tab && tabs.some((t) => t.key === tab)) setActiveTab(tab);
    } catch {
      /* non-browser or malformed query — ignore */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="h-full space-y-5 overflow-y-auto p-4 sm:p-6">
      {/* Header */}
      {/* Stacks until xl. The sidebar eats ~220px, so at 1024 the content column
          is only ~800px and a side-by-side header still wrapped the subtitle,
          the status pill and "Create location" onto two lines each. */}
      <div className="flex flex-col items-start gap-3 xl:flex-row xl:items-start xl:justify-between xl:gap-4">
        <div className="min-w-0">
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">{copy.title}</h1>
          <p className="mt-0.5 text-[13px] text-ink/45 dark:text-fog/45">
            {copy.subtitle}
          </p>
        </div>
        <div className="flex flex-col items-stretch gap-3 xl:flex-row xl:items-center">
          {/* Location selector dropdown — "All branches" enables bulk edit */}
          <div className="relative w-full xl:w-auto xl:min-w-56">
            <select
              value={selectedId ?? ""}
              onChange={(e) => {
                setSelectedId(e.target.value);
                setLastBulkFail(null);
              }}
              className="w-full appearance-none rounded-xl border border-ink/[0.08] bg-white py-2 pl-3 pr-9 text-[13px] font-medium text-ink outline-none transition focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              {locations.length > 1 && (
                <option value={ALL}>{copy.allBranches.replace("{count}", String(locations.length))}</option>
              )}
              {groups.map((g) => (
                <option key={g.id} value={groupValue(g.id)}>
                  {g.name} ({g.listing_ids.filter((id) => locations.some((l) => l.id === id)).length})
                </option>
              ))}
              {locations.map((loc) => (
                <option key={loc.id} value={loc.id}>
                  {loc.name}
                </option>
              ))}
              {locations.length === 0 && <option value="">{copy.noLocations}</option>}
            </select>
            <svg className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink/40 dark:text-fog/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </div>
          <div className="flex w-full flex-wrap items-center gap-3 xl:w-auto xl:flex-nowrap">
            <button
              onClick={() => setGroupsOpen(true)}
              className="min-h-9 rounded-xl border border-ink/[0.08] bg-white px-3.5 py-2 text-[12px] font-semibold text-ink transition hover:border-deep-violet/30 hover:bg-ink/[0.02] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
            >
              {copy.manageGroups}
              {groups.length > 0 && (
                <span className="ms-1.5 rounded-full bg-deep-violet/10 px-1.5 py-0.5 text-[10px] font-bold text-deep-violet">
                  {groups.length}
                </span>
              )}
            </button>
            <span className={`rounded-full px-3 py-1.5 text-[11px] font-bold ${locations.length ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700"}`}>
              {locations.length ? copy.googleConnected : copy.googleNotConnected}
            </span>
            <button
              onClick={() => setCreateOpen(true)}
              title={copy.createLocationTitle}
              data-tour="add-location"
              className="min-h-9 rounded-xl bg-deep-violet px-3.5 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:opacity-90"
            >
              {copy.createLocation}
            </button>
          </div>
        </div>
      </div>

      {/* Multi-location hint */}
      {locations.length > 0 && !isBulk && (
        <p className="rounded-xl border border-ink/[0.06] bg-white/60 p-3 text-[12px] text-ink/50 dark:border-fog/[0.06] dark:bg-ink/60 dark:text-fog/50">
          {copy.multiLocationHint}
        </p>
      )}

      {/* Bulk scope banner — unmissable: button labels and receipts repeat it */}
      {isBulk && locations.length > 0 && (
        <div className="rounded-xl border-2 border-amber-300 bg-amber-50 p-3 text-[12.5px] dark:border-amber-500/40 dark:bg-amber-500/[0.08]">
          <p className="font-bold text-amber-800 dark:text-amber-200">
            {copy.bulkEditingAll
              .replace("{count}", String(locations.length))
              .replace("{branches}", locations.map((l) => l.name).join(", "))}
          </p>
          <p className="mt-0.5 text-amber-700/80 dark:text-amber-200/70">
            {copy.bulkEditingAllSub}
          </p>
        </div>
      )}

      {/* Banner */}
      {banner && (
        <div className={`rounded-xl border p-3 text-[13px] ${banner.kind === "ok" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-red-200 bg-red-50 text-red-700"}`}>
          <div className="flex items-center justify-between gap-3">
            <span>{banner.text}</span>
            <button className="shrink-0 text-[12px] underline underline-offset-2" onClick={() => setBanner(null)}>{copy.dismiss}</button>
          </div>
        </div>
      )}

      {/* Bulk retry — re-runs the same save for failed branches only */}
      {lastBulkFail && (
        <div className="flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-[13px] text-red-700">
          <span>
            {lastBulkFail.label} failed on: {lastBulkFail.failed.map((f) => f.name).join(", ")}.
          </span>
          <button
            onClick={lastBulkFail.onRetry}
            className="shrink-0 rounded-lg bg-red-600 px-3 py-1.5 text-[12px] font-semibold text-white transition hover:bg-red-700"
          >
            Retry failed ({lastBulkFail.failed.length})
          </button>
        </div>
      )}

      {/* Bulk confirm sheet — the final guard before a mass edit */}
      {confirmBulk && (
        <div
          role="alertdialog"
          aria-modal="true"
          aria-label="Confirm bulk edit"
          className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-sm"
        >
          <div className="w-full max-w-md rounded-2xl border border-ink/[0.06] bg-white p-5 shadow-2xl dark:border-fog/[0.08] dark:bg-ink">
            <h2 className="text-[15px] font-bold text-ink dark:text-fog">
              {confirmBulk.title}
            </h2>
            <p className="mt-1 text-[12px] text-ink/50 dark:text-fog/50">
              Applies to {confirmBulk.branches.length} branches:{" "}
              {confirmBulk.branches.map((b) => b.name).join(", ")}
            </p>
            <ul className="mt-3 max-h-48 space-y-1.5 overflow-y-auto rounded-xl bg-ink/[0.03] p-3 text-[12.5px] text-ink/70 dark:bg-fog/[0.04] dark:text-fog/70">
              {confirmBulk.lines.map((line, i) => (
                <li key={i} className="flex gap-2">
                  <span aria-hidden className="text-deep-violet">•</span>
                  <span className="break-words">{line}</span>
                </li>
              ))}
            </ul>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setConfirmBulk(null)}
                disabled={confirmBulk.busy}
                className="rounded-lg px-3.5 py-2 text-[12px] font-semibold text-ink/60 transition hover:bg-ink/[0.04] dark:text-fog/60 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmBulk.onConfirm}
                disabled={confirmBulk.busy}
                className="rounded-lg bg-amber-500 px-3.5 py-2 text-[12px] font-bold text-white shadow-sm transition hover:bg-amber-600 disabled:opacity-50"
              >
                {confirmBulk.busy
                  ? "Applying..."
                  : `Apply to ${confirmBulk.branches.length} branch${confirmBulk.branches.length === 1 ? "" : "es"}`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Location groups — create, rename, reassign members */}
      {groupsOpen && (
        <GroupsModal
          groups={groups}
          locations={locations}
          copy={copy}
          onClose={() => setGroupsOpen(false)}
          onChanged={(next) => {
            setGroups(next);
            /* If the open group just lost members or was deleted, fall back
               to a single location rather than an empty bulk scope. */
            if (selectedGroupId) {
              const still = next.find((g) => g.id === selectedGroupId);
              if (!still) setSelectedId(locations[0]?.id ?? null);
              else if (!locations.some((l) => l.id === still.listing_ids[0])) setSelectedId(locations[0]?.id ?? null);
            }
          }}
        />
      )}

      {/* Add-location wizard (Google create workflow, draft-only until Google connects) */}
      {createOpen && (
        <AddLocationModal
          onClose={() => setCreateOpen(false)}
          onSaved={(text) => {
            setCreateOpen(false);
            showBanner("ok", text);
          }}
        />
      )}

      {/* Profile completeness (Localith snapshot) — per-branch only */}
      {!isBulk && localith && <CompletenessCard profile={localith} fullProfile={fullProfile} copy={copy} />}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <LogoLoader size={32} />
        </div>
      ) : (
        <>
          {/* Tabs (google-updates is per-branch, hidden in bulk) */}
          <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
            <div role="tablist" className="flex gap-1 rounded-xl bg-ink/[0.03] p-1 dark:bg-fog/[0.04]">
              {tabs.filter((tab) => !isBulk || tab.key !== "google-updates").map((tab) => (
                <button
                  key={tab.key}
                  role="tab"
                  aria-selected={activeTab === tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`min-h-9 whitespace-nowrap rounded-lg px-3 py-1.5 text-[12px] font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                    activeTab === tab.key
                      ? "bg-white text-deep-violet shadow-sm dark:bg-ink dark:text-fog"
                      : "text-ink/45 hover:text-ink/70 dark:text-fog/45"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
          {!isBulk && locations.length > 1 && (
            <p className="rounded-xl border border-deep-violet/15 bg-deep-violet/[0.04] px-3.5 py-2 text-[12px] text-ink/55 dark:text-fog/55">
              💡 {copy.bulkTipBefore}{" "}
              <button
                onClick={() => setSelectedId(ALL)}
                className="font-bold text-deep-violet underline underline-offset-2 outline-none transition hover:text-deep-violet/80 focus-visible:ring-2 focus-visible:ring-deep-violet/40"
              >
                {t.dashboard.pulse.allBusinesses}
              </button>{" "}
              {copy.bulkTipAfter}
            </p>
          )}

          {/* Tab content */}
          <div className="rounded-2xl border border-ink/[0.06] bg-white p-4 sm:p-5 dark:border-fog/[0.06] dark:bg-ink">
            {activeTab === "details" && (
              <DetailsTab
                location={selectedLocation}
                profile={isBulk ? null : localith}
                fullProfile={isBulk ? null : fullProfile}
                copy={copy}
                onSave={(text, kind) => showBanner(kind ?? "ok", text)}
                onProfile={async (c) => {
                  setLocalith(c);
                  if (selectedId && !isBulk) {
                    try {
                      const refreshed = await apiFetch(`/api/v1/locations/${selectedId}`);
                      setFullProfile(refreshed as FullProfile);
                    } catch {
                      /* ignore refresh failure — locations update already applied */
                    }
                  }
                }}
                bulk={bulk}
                onBulkSave={
                  bulk
                    ? (data) => {
                        const lines = [
                          `Phone → ${data.phone || "(cleared)"}`,
                          `Website → ${data.website || "(cleared)"}`,
                        ];
                        requestBulkSave(
                          "Apply business details to all branches?",
                          lines,
                          () => runBulkDetails(data),
                          "Details",
                          (ids) => runBulkDetails(data, ids),
                        );
                      }
                    : null
                }
              />
            )}
            {activeTab === "categories" && (
              <CategoriesTab
                initial={isBulk ? undefined : fullProfile?.categories}
                bulk={bulk}
                copy={copy}
                onSave={(patch) =>
                  isBulk
                    ? bulkSaveProfile(copy.tabCategories, { categories: patch }, [
                        `${copy.primaryCategory} → ${patch.primary || copy.cleared}`,
                        `${copy.additionalCategories} (${patch.additional.length}): ${patch.additional.join(", ") || copy.cleared}`,
                      ])
                    : saveProfile({ categories: patch }, copy.categoriesSaved)
                }
              />
            )}
            {activeTab === "hours" && (
              <HoursTab
                initial={isBulk ? undefined : fullProfile?.hours?.regular}
                bulk={bulk}
                copy={copy}
                onSave={(regular) =>
                  isBulk
                    ? bulkSaveProfile(copy.tabHours, { hours: { regular } }, describeHours(regular, copy))
                    : saveProfile({ hours: { regular } }, copy.hoursSaved)
                }
              />
            )}
            {activeTab === "special-hours" && (
              <SpecialHoursTab
                initial={isBulk ? undefined : fullProfile?.hours?.special}
                bulk={bulk}
                copy={copy}
                onSave={(special) =>
                  isBulk
                    ? bulkSaveProfile(copy.specialHoursTitle, { hours: { special } }, [
                        copy.specialHoursCount.replace("{count}", String(special.length)),
                        ...special.slice(0, 8).map(
                          (e) => `${e.date || "?"}: ${e.hours}${e.reason ? ` (${e.reason})` : ""}`
                        ),
                      ])
                    : saveProfile({ hours: { special } }, copy.specialHoursSaved)
                }
              />
            )}
            {activeTab === "more-hours" && (
              <MoreHoursTab
                initial={isBulk ? undefined : fullProfile?.hours?.more}
                bulk={bulk}
                copy={copy}
                onSave={(more) =>
                  isBulk
                    ? bulkSaveProfile(copy.tabMoreHours, { hours: { more } }, [
                        copy.moreHoursCount.replace("{count}", String(more.length)),
                        ...more
                          .slice(0, 8)
                          .map(
                            (e) =>
                              `${serviceTypeLabel(e.type, copy)}: ${e.open}–${e.close}`
                          ),
                      ])
                    : saveProfile({ hours: { more } }, copy.moreHoursSaved)
                }
              />
            )}
            {activeTab === "service-area" && (
              <ServiceAreaTab
                initial={isBulk ? undefined : fullProfile?.service_area}
                bulk={bulk}
                copy={copy}
                onSave={(service_area) =>
                  isBulk
                    ? bulkSaveProfile(copy.tabServiceArea, { service_area }, [
                        service_area.length === 0
                          ? copy.serviceAreaCleared
                          : copy.serviceAreaSummary.replace("{areas}", service_area.join(", ")),
                      ])
                    : saveProfile({ service_area }, copy.serviceAreaSaved)
                }
              />
            )}
            {activeTab === "attributes" && (
              <AttributesTab
                initial={isBulk ? undefined : fullProfile?.attributes}
                bulk={bulk}
                copy={copy}
                onSave={(attributes) =>
                  isBulk
                    ? bulkSaveProfile(
                        copy.tabAttributes,
                        { attributes },
                        Object.keys(attributes).length === 0
                          ? [copy.attributesCleared]
                          : Object.entries(attributes).map(([k, v]) => `${k}: ${v}`)
                      )
                    : saveProfile({ attributes }, copy.attributesSaved)
                }
              />
            )}
            {activeTab === "description" && (
              <DescriptionTab
                initial={isBulk ? "" : fullProfile?.description ?? ""}
                initialOpeningDate={isBulk ? null : fullProfile?.opening_date ?? null}
                bulk={bulk}
                copy={copy}
                onSave={(description, openingDate) =>
                  isBulk
                    ? bulkSaveProfile(copy.tabDescription, { description, opening_date: openingDate }, [
                        copy.descriptionSummary.replace(
                          "{text}",
                          `${description.slice(0, 120)}${description.length > 120 ? "…" : ""}`
                        ),
                      ])
                    : saveProfile({ description, opening_date: openingDate }, copy.descriptionSaved)
                }
              />
            )}
            {activeTab === "google-updates" && (
              <GoogleUpdatesTab copy={copy} />
            )}
          </div>

        </>
      )}
    </div>
  );
}

/* ── Tab Panels ──────────────────────────────────── */

function DetailsTab({
  location,
  profile,
  fullProfile,
  onSave,
  onProfile,
  bulk,
  onBulkSave,
  copy,
}: {
  location: LocationOption | null;
  profile: LocalithConn | null;
  fullProfile?: FullProfile | null;
  onSave: (text: string, kind?: "ok" | "err") => void;
  onProfile: (c: LocalithConn) => void;
  bulk?: BulkScope | null;
  onBulkSave?: ((data: { phone: string; website: string }) => void) | null;
  copy: LocationsCopy;
}) {
  const displayName = fullProfile?.name ?? location?.name ?? "";
  const [name, setName] = useState(displayName);
  const [address, setAddress] = useState(location?.address ?? "");
  const [phone, setPhone] = useState(profile?.phone_number ?? "");
  const [website, setWebsite] = useState(profile?.website_url ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setName(fullProfile?.name ?? location?.name ?? "");
    setAddress(location?.address ?? "");
    setPhone(profile?.phone_number ?? "");
    setWebsite(profile?.website_url ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location?.id, profile?.listing_id, fullProfile?.name]);

  const handleSave = async () => {
    if (bulk && onBulkSave) {
      onBulkSave({ phone: phone.trim(), website: website.trim() });
      return;
    }
    if (!profile) {
      onSave("Details saved.");
      return;
    }
    setSaving(true);
    try {
      const updated = await apiFetch("/api/v1/integrations/localith/listing", {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim() || undefined,
          phone_number: phone.trim() || undefined,
          website_url: website.trim() || undefined,
        }),
      });
      onProfile(updated as LocalithConn);
      onSave("Details saved to Google via Localith.", "ok");
    } catch (e) {
      onSave(e instanceof Error ? e.message.slice(0, 160) : "Could not save details.", "err");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <SectionTitle title={copy.tabDetails} subtitle={copy.detailsSubtitle} />
        <SourceBadge google={!!profile} copy={copy} />
      </div>
      {profile && (
        <p className="-mt-2 text-[11px] text-ink/45 dark:text-fog/45">
          {copy.syncedViaLocalith}
          {profile.maps_url && (
            <> · <a href={profile.maps_url} target="_blank" rel="noreferrer" className="font-semibold text-deep-violet underline underline-offset-2">{copy.viewOnMaps}</a></>
          )}
        </p>
      )}
      {!bulk && (
        <>
          <Field label={copy.essentialName}>
            <input value={name} onChange={(e) => setName(e.target.value)} className="input-field" />
          </Field>
          <Field label={copy.essentialAddress}>
            <input
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              readOnly={!!profile}
              title={profile ? copy.addressReadOnlyTitle : undefined}
              className={`input-field ${profile ? "opacity-60" : ""}`}
            />
          </Field>
        </>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={copy.fieldPhone} varies={bulk?.varies.has("phone") ?? false}>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+966 55 000 0000" className="input-field" />
          {bulk?.fieldValues?.phone ? (
            <BranchValues
              branches={bulk.branches}
              values={bulk.fieldValues.phone}
              missingLabel={copy.notSet}
            />
          ) : null}
        </Field>
        <Field label={copy.fieldWebsite} varies={bulk?.varies.has("website") ?? false}>
          <input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://..." className="input-field" />
          {bulk?.fieldValues?.website ? (
            <BranchValues
              branches={bulk.branches}
              values={bulk.fieldValues.website}
              missingLabel={copy.notSet}
            />
          ) : null}
        </Field>
      </div>
      {!bulk && (
        <Field label={copy.fieldStatus}>
          <div className="flex items-center gap-2">
            <span className={`inline-flex h-5 w-5 items-center justify-center rounded-full ${location?.status === "active" ? "bg-emerald-100 text-emerald-600" : "bg-ink/10 text-ink/40"}`}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="h-3 w-3"><path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" /></svg>
            </span>
            <span className="text-[13px] text-ink dark:text-fog">
              {statusLabel(location?.status, copy)}
            </span>
          </div>
        </Field>
      )}
      <div className="pt-2 sm:flex sm:justify-end">
        <button onClick={handleSave} disabled={saving} className="btn-primary w-full justify-center sm:w-auto">
          {saving
            ? <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> {copy.saving}</span>
            : bulk
              ? copy.applyToBranches.replace("{count}", String(bulk.branches.length))
              : copy.saveChanges}
        </button>
      </div>
    </div>
  );
}

function CategoriesTab({ initial, onSave, bulk, copy }: {
  initial?: { primary?: string; additional?: string[] };
  onSave: (patch: { primary: string; additional: string[] }) => Promise<void>;
  bulk?: BulkScope | null;
  copy: LocationsCopy;
}) {
  const [primary, setPrimary] = useState(initial?.primary ?? "");
  const [additional, setAdditional] = useState<string[]>(initial?.additional ?? []);
  const [newCat, setNewCat] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setPrimary(initial?.primary ?? "");
    setAdditional(initial?.additional ?? []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initial)]);

  const addCategory = () => {
    if (newCat.trim() && !additional.includes(newCat.trim())) {
      setAdditional([...additional, newCat.trim()]);
      setNewCat("");
    }
  };

  const removeCategory = (cat: string) => setAdditional(additional.filter((c) => c !== cat));

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave({ primary: primary.trim(), additional });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <SectionTitle title={copy.tabCategories} subtitle={copy.categoriesSubtitle} />
        <SourceBadge google={false} copy={copy} />
      </div>
      <Field label={copy.primaryCategory} varies={bulk?.varies.has("primary") ?? false}>
        <input value={primary} onChange={(e) => setPrimary(e.target.value)} placeholder={copy.primaryCategoryPlaceholder} className="input-field" />
        <p className="mt-1 text-[11px] text-ink/40 dark:text-fog/40">{copy.primaryCategoryHint}</p>
      </Field>
      <Field label={copy.additionalCategories} varies={bulk?.varies.has("additional") ?? false}>
        <p className="mb-2 text-[11px] text-ink/40 dark:text-fog/40">{copy.additionalCategoriesHint}</p>
        {/* Google's own taxonomy — the values sent to Google must stay in the
            exact wording Google recognises, so these chips are not translated. */}
        <div className="mb-2 flex flex-wrap gap-1.5">
          {["Restaurant", "Cafe", "Dental clinic", "Pharmacy", "Beauty salon", "Car wash"].filter((c) => !additional.includes(c)).map((c) => (
            <button key={c} onClick={() => setAdditional([...additional, c])} className="rounded-full bg-ink/[0.04] px-2.5 py-1 text-[11px] font-medium text-ink/60 transition hover:bg-deep-violet/10 hover:text-deep-violet dark:bg-fog/[0.06] dark:text-fog/60">
              + {c}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 mb-2">
          {additional.map((cat) => (
            <span key={cat} className="inline-flex items-center gap-1 rounded-full bg-deep-violet/10 px-2.5 py-1 text-[12px] font-medium text-deep-violet">
              {cat}
              <button onClick={() => removeCategory(cat)} className="ml-0.5 text-deep-violet/50 hover:text-deep-violet">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
              </button>
            </span>
          ))}
        </div>
        <div className="grid grid-cols-[1fr_auto] items-center gap-2">
          <input value={newCat} onChange={(e) => setNewCat(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addCategory()} placeholder={copy.addCategoryPlaceholder} className="input-field" />
          <button onClick={addCategory} className="btn-secondary">{copy.add}</button>
        </div>
      </Field>
      <div className="pt-2 sm:flex sm:justify-end">
        <button onClick={handleSave} disabled={saving} className="btn-primary disabled:opacity-50">
          {saving
            ? copy.saving
            : bulk
              ? copy.applyToBranches.replace("{count}", String(bulk.branches.length))
              : copy.saveCategories}
        </button>
      </div>
    </div>
  );
}

function HoursTab({ initial, onSave, bulk, copy }: {
  initial?: Record<string, { open: string; close: string; closed: boolean }>;
  onSave: (regular: Record<string, { open: string; close: string; closed: boolean }>) => Promise<void>;
  bulk?: BulkScope | null;
  copy: LocationsCopy;
}) {
  const blank = () => Object.fromEntries(HOURS_DAYS.map((d) => [d, { open: "", close: "", closed: false }]));
  const [hours, setHours] = useState<Record<string, { open: string; close: string; closed: boolean }>>(
    { ...blank(), ...(initial ?? {}) }
  );
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset form when switching locations
    setHours({ ...blank(), ...(initial ?? {}) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initial)]);

  const updateDay = (day: string, field: string, value: string | boolean) => {
    setHours({ ...hours, [day]: { ...hours[day], [field]: value } });
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(hours);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <SectionTitle title={copy.regularHours} subtitle={copy.regularHoursSubtitle} />
        <div className="flex items-center gap-2">
          {bulk?.varies.has("hours") ? <VariesBadge /> : null}
          <SourceBadge google={false} copy={copy} />
        </div>
      </div>
      <p className="-mt-2 text-[11px] text-ink/40 dark:text-fog/40">{copy.hoursHint}</p>
      <div className="space-y-2">
        {HOURS_DAYS.map((day) => (
          <div key={day} className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 sm:flex-nowrap dark:border-fog/[0.06] dark:bg-fog/[0.02]">
            <span className="w-24 shrink-0 text-[13px] font-medium text-ink dark:text-fog">{dayLabel(day, copy)}</span>
            <label className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={!hours[day].closed}
                onChange={(e) => updateDay(day, "closed", !e.target.checked)}
                className="h-4 w-4 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/40"
              />
              <span className="text-[12px] text-ink/50 dark:text-fog/50">{copy.openLabel}</span>
            </label>
            {!hours[day].closed ? (
              <div className="flex items-center gap-2">
                <input type="time" value={hours[day].open} onChange={(e) => updateDay(day, "open", e.target.value)} className="input-field w-28" />
                <span className="text-[12px] text-ink/40">{copy.toLabel}</span>
                <input type="time" value={hours[day].close} onChange={(e) => updateDay(day, "close", e.target.value)} className="input-field w-28" />
              </div>
            ) : (
              <span className="text-[12px] font-medium text-ink/30 dark:text-fog/30">{copy.closedLabel}</span>
            )}
          </div>
        ))}
      </div>
      <div className="pt-2 sm:flex sm:justify-end">
        <button onClick={handleSave} disabled={saving} className="btn-primary disabled:opacity-50">
          {saving
            ? copy.saving
            : bulk
              ? copy.applyToBranches.replace("{count}", String(bulk.branches.length))
              : copy.saveHours}
        </button>
      </div>
    </div>
  );
}

function SpecialHoursTab({ initial, onSave, bulk, copy }: {
  initial?: { date: string; hours: string; reason: string }[];
  onSave: (special: { date: string; hours: string; reason: string }[]) => Promise<void>;
  bulk?: BulkScope | null;
  copy: LocationsCopy;
}) {
  const [entries, setEntries] = useState<{ date: string; hours: string; reason: string }[]>(initial ?? []);
  const [saving, setSaving] = useState(false);
  const addEntry = () => setEntries([...entries, { date: "", hours: "09:00 - 17:00", reason: "" }]);
  const removeEntry = (i: number) => setEntries(entries.filter((_, idx) => idx !== i));
  const updateEntry = (i: number, field: string, value: string) => {
    const next = [...entries];
    (next[i] as any)[field] = value;
    setEntries(next);
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset form when switching locations
    setEntries(initial ?? []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initial)]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(entries);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <SectionTitle title={copy.specialHoursTitle} subtitle={copy.specialHoursSubtitle} />
        <div className="flex items-center gap-2">
          {bulk?.varies.has("special") ? <VariesBadge /> : null}
          <SourceBadge google={false} copy={copy} />
        </div>
      </div>
      <p className="-mt-2 text-[11px] text-ink/40 dark:text-fog/40">{copy.specialHoursHint}</p>
      {entries.map((entry, i) => (
        <div key={i} className="grid grid-cols-1 items-start gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 sm:grid-cols-[150px_150px_1fr_auto] dark:border-fog/[0.06] dark:bg-fog/[0.02]">
          <input type="date" value={entry.date} onChange={(e) => updateEntry(i, "date", e.target.value)} className="input-field" />
          {/* "09:00 - 17:00" / "closed" are Google wire values — not translated. */}
          <input value={entry.hours} onChange={(e) => updateEntry(i, "hours", e.target.value)} placeholder="09:00 - 17:00" className="input-field" />
          <input value={entry.reason} onChange={(e) => updateEntry(i, "reason", e.target.value)} placeholder={copy.reasonPlaceholder} className="input-field" />
          <button onClick={() => removeEntry(i)} className="mt-1 text-ink/30 transition hover:text-red-500 dark:text-fog/30">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
          </button>
        </div>
      ))}
      <button onClick={addEntry} className="btn-secondary">{copy.addSpecialHours}</button>
      <div className="pt-2 sm:flex sm:justify-end">
        <button onClick={handleSave} disabled={saving} className="btn-primary disabled:opacity-50">
          {saving
            ? copy.saving
            : bulk
              ? copy.applyToBranches.replace("{count}", String(bulk.branches.length))
              : copy.saveSpecialHours}
        </button>
      </div>
    </div>
  );
}

// Google wire values for additionalHoursTypes — stored and sent as-is, so these
// stay English. MORE_HOURS_TYPE_KEYS only localises the visible option label.
const MORE_HOURS_OPTIONS = ["Access", "Brunch", "Delivery", "Dinner", "Happy Hour", "Lunch", "Takeout", "Drive-through"];

const MORE_HOURS_TYPE_KEYS = {
  Access: "typeAccess",
  Brunch: "typeBrunch",
  Delivery: "typeDelivery",
  Dinner: "typeDinner",
  "Happy Hour": "typeHappyHour",
  Lunch: "typeLunch",
  Takeout: "typeTakeout",
  "Drive-through": "typeDriveThrough",
} as const;

const serviceTypeLabel = (type: string, copy: LocationsCopy): string => {
  const key = MORE_HOURS_TYPE_KEYS[type as keyof typeof MORE_HOURS_TYPE_KEYS];
  return key ? copy[key] : type;
};

function MoreHoursTab({ initial, onSave, bulk, copy }: {
  initial?: { type: string; open: string; close: string }[];
  onSave: (more: { type: string; open: string; close: string }[]) => Promise<void>;
  bulk?: BulkScope | null;
  copy: LocationsCopy;
}) {
  const [entries, setEntries] = useState<{ type: string; open: string; close: string }[]>(initial ?? []);
  const [saving, setSaving] = useState(false);
  const addEntry = () => setEntries([...entries, { type: MORE_HOURS_OPTIONS[0], open: "09:00", close: "17:00" }]);
  const removeEntry = (i: number) => setEntries(entries.filter((_, idx) => idx !== i));
  const updateEntry = (i: number, field: string, value: string) => {
    const next = [...entries];
    (next[i] as any)[field] = value;
    setEntries(next);
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset form when switching locations
    setEntries(initial ?? []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initial)]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(entries);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <SectionTitle title={copy.tabMoreHours} subtitle={copy.moreHoursSubtitle} />
        <div className="flex items-center gap-2">
          {bulk?.varies.has("more") ? <VariesBadge /> : null}
          <SourceBadge google={false} copy={copy} />
        </div>
      </div>
      <p className="-mt-2 text-[11px] text-ink/40 dark:text-fog/40">{copy.moreHoursHint}</p>
      {entries.length === 0 && (
        <p className="text-[12px] text-ink/35 dark:text-fog/35">{copy.moreHoursEmpty}</p>
      )}
      {entries.map((entry, i) => (
        <div key={i} className="grid grid-cols-1 items-center gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 sm:grid-cols-[150px_120px_auto_120px_auto] dark:border-fog/[0.06] dark:bg-fog/[0.02]">
          <select value={entry.type} onChange={(e) => updateEntry(i, "type", e.target.value)} className="input-field">
            {/* value stays the English wire value; only the label is localised */}
            {MORE_HOURS_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>{serviceTypeLabel(opt, copy)}</option>
            ))}
          </select>
          <input type="time" value={entry.open} onChange={(e) => updateEntry(i, "open", e.target.value)} className="input-field" />
          <span className="text-[12px] text-ink/40">{copy.toLabel}</span>
          <input type="time" value={entry.close} onChange={(e) => updateEntry(i, "close", e.target.value)} className="input-field" />
          <button onClick={() => removeEntry(i)} className="text-ink/30 transition hover:text-red-500 dark:text-fog/30">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
          </button>
        </div>
      ))}
      <button onClick={addEntry} className="btn-secondary">{copy.addMoreHours}</button>
      <div className="pt-2 sm:flex sm:justify-end">
        <button onClick={handleSave} disabled={saving} className="btn-primary disabled:opacity-50">
          {saving
            ? copy.saving
            : bulk
              ? copy.applyToBranches.replace("{count}", String(bulk.branches.length))
              : copy.saveMoreHours}
        </button>
      </div>
    </div>
  );
}

function ServiceAreaTab({ initial, onSave, bulk, copy }: {
  initial?: string[];
  onSave: (areas: string[]) => Promise<void>;
  bulk?: BulkScope | null;
  copy: LocationsCopy;
}) {
  const [areas, setAreas] = useState<string[]>(initial ?? []);
  const [newArea, setNewArea] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset form when switching locations
    setAreas(initial ?? []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initial)]);

  const addArea = () => {
    if (newArea.trim() && !areas.includes(newArea.trim())) {
      setAreas([...areas, newArea.trim()]);
      setNewArea("");
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(areas);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <SectionTitle title={copy.tabServiceArea} subtitle={copy.serviceAreaSubtitle} />
        <div className="flex items-center gap-2">
          {bulk?.varies.has("service_area") ? <VariesBadge /> : null}
          <SourceBadge google={false} copy={copy} />
        </div>
      </div>
      <p className="-mt-2 text-[11px] text-ink/40 dark:text-fog/40">{copy.serviceAreaHint}</p>
      <div className="flex flex-wrap gap-2 mb-3">
        {areas.map((area) => (
          <span key={area} className="inline-flex items-center gap-1 rounded-full bg-sky-100 px-2.5 py-1 text-[12px] font-medium text-sky-700 dark:bg-sky-500/10 dark:text-sky-300">
            {area}
            <button onClick={() => setAreas(areas.filter((a) => a !== area))} className="ml-0.5 text-sky-500/50 hover:text-sky-700">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-3 w-3"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
            </button>
          </span>
        ))}
      </div>
      <div className="grid grid-cols-[1fr_auto] items-center gap-2">
        <input value={newArea} onChange={(e) => setNewArea(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addArea()} placeholder={copy.serviceAreaPlaceholder} className="input-field" />
        <button onClick={addArea} className="btn-secondary">{copy.add}</button>
      </div>
      <div className="pt-2 sm:flex sm:justify-end">
        <button onClick={handleSave} disabled={saving} className="btn-primary disabled:opacity-50">
          {saving
            ? copy.saving
            : bulk
              ? copy.applyToBranches.replace("{count}", String(bulk.branches.length))
              : copy.saveServiceArea}
        </button>
      </div>
    </div>
  );
}

// Attribute values are compared against the API's _TRUE/_FALSE sets, so the
// stored value stays English; only the visible option label is localised.
const ATTRIBUTE_VALUE_OPTIONS = ["yes", "no", "limited"] as const;

const ATTRIBUTE_VALUE_KEYS = {
  yes: (c: LocationsCopy) => c.attrYes,
  no: (c: LocationsCopy) => c.attrNo,
  limited: (c: LocationsCopy) => c.attrLimited,
} as const satisfies Record<string, (c: LocationsCopy) => string>;

function AttributesTab({ initial, onSave, bulk, copy }: {
  initial?: Record<string, string>;
  onSave: (attrs: Record<string, string>) => Promise<void>;
  bulk?: BulkScope | null;
  copy: LocationsCopy;
}) {
  const [attrs, setAttrs] = useState<Record<string, string>>(initial ?? {});
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("yes");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset form when switching locations
    setAttrs(initial ?? {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initial)]);

  const addAttr = () => {
    const k = newKey.trim();
    if (k && !(k in attrs)) {
      setAttrs({ ...attrs, [k]: newValue.trim() || "yes" });
      setNewKey("");
      setNewValue("yes");
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(attrs);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <SectionTitle title={copy.tabAttributes} subtitle={copy.attributesSubtitle} />
        <div className="flex items-center gap-2">
          {bulk?.varies.has("attributes") ? <VariesBadge /> : null}
          <SourceBadge google={false} copy={copy} />
        </div>
      </div>
      <p className="-mt-2 text-[11px] text-ink/40 dark:text-fog/40">{copy.attributesHint}</p>
      <div className="flex flex-wrap gap-1.5">
        {[["Wheelchair accessible entrance", "yes"], ["Free WiFi", "yes"], ["Outdoor seating", "yes"], ["Accepts credit cards", "yes"]].filter(([k]) => !(k in attrs)).map(([k, v]) => (
          <button key={k} onClick={() => { setNewKey(k); setNewValue(v); }} className="rounded-full bg-ink/[0.04] px-2.5 py-1 text-[11px] font-medium text-ink/60 transition hover:bg-deep-violet/10 hover:text-deep-violet dark:bg-fog/[0.06] dark:text-fog/60">
            + {k}: {v}
          </button>
        ))}
      </div>
      <div className="space-y-3">
        {Object.entries(attrs).length === 0 && <p className="text-[12px] text-ink/35 dark:text-fog/35">{copy.attributesEmpty}</p>}
        {Object.entries(attrs).map(([key, value]) => (
          <div key={key} className="grid grid-cols-[1fr_160px_auto] items-center gap-3">
            {/* key is Google's attribute vocabulary (matched against ATTRIBUTE_IDS) — stays English */}
            <span className="truncate text-[13px] font-medium text-ink dark:text-fog" title={key}>{key}</span>
            <input
              value={value}
              onChange={(e) => setAttrs({ ...attrs, [key]: e.target.value })}
              className="input-field"
            />
            <button
              onClick={() => setAttrs(Object.fromEntries(Object.entries(attrs).filter(([k]) => k !== key)))}
              aria-label={copy.removeAttribute.replace("{name}", key)}
              className="text-ink/30 transition hover:text-red-500 dark:text-fog/30"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="h-4 w-4"><path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" /></svg>
            </button>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 items-center gap-3 sm:grid-cols-[1fr_140px_auto]">
        <input value={newKey} onChange={(e) => setNewKey(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addAttr()} placeholder={copy.attributesKeyPlaceholder} className="input-field" />
        {/* value is matched against the API's _TRUE/_FALSE sets — keep English on the wire, localise the label only */}
        <select value={newValue} onChange={(e) => setNewValue(e.target.value)} aria-label={copy.attributeValueLabel} className="input-field cursor-pointer text-center text-[12px] font-bold">
          {ATTRIBUTE_VALUE_OPTIONS.map((v) => (
            <option key={v} value={v}>{ATTRIBUTE_VALUE_KEYS[v](copy)}</option>
          ))}
        </select>
        <button onClick={addAttr} className="btn-secondary justify-self-start sm:justify-self-auto">{copy.add}</button>
      </div>
      <div className="pt-2 sm:flex sm:justify-end">
        <button onClick={handleSave} disabled={saving} className="btn-primary disabled:opacity-50">
          {saving
            ? copy.saving
            : bulk
              ? copy.applyToBranches.replace("{count}", String(bulk.branches.length))
              : copy.saveAttributes}
        </button>
      </div>
    </div>
  );
}

function DescriptionTab({ initial, initialOpeningDate, onSave, bulk, copy }: {
  initial?: string;
  initialOpeningDate?: string | null;
  onSave: (description: string, openingDate: string | null) => Promise<void>;
  bulk?: BulkScope | null;
  copy: LocationsCopy;
}) {
  const [desc, setDesc] = useState(initial ?? "");
  const [openingDate, setOpeningDate] = useState(initialOpeningDate ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset form when switching locations
    setDesc(initial ?? "");
    setOpeningDate(initialOpeningDate ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(initial), initialOpeningDate]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(desc.trim(), openingDate || null);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-col items-start gap-1.5 sm:flex-row sm:items-start sm:justify-between sm:gap-3">
        <SectionTitle title={copy.descriptionTitle} subtitle={copy.descriptionSubtitle} />
        <div className="flex items-center gap-2">
          {bulk?.varies.has("description") ? <VariesBadge /> : null}
          <SourceBadge google copy={copy} />
        </div>
      </div>
      <textarea
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        rows={6}
        maxLength={750}
        placeholder={copy.descriptionPlaceholder}
        className="w-full resize-y rounded-xl border border-ink/[0.08] bg-white p-3 text-[13px] text-ink outline-none transition placeholder:text-ink/25 focus:border-deep-violet/30 focus:ring-2 focus:ring-deep-violet/[0.1] dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
      />
      <p className="text-right text-[11px] text-ink/30 dark:text-fog/30">
        {copy.descriptionCounter.replace("{count}", String(desc.length))}
      </p>
      <div>
        <label className="mb-1 block text-[12px] font-medium text-ink/60 dark:text-fog/60">
          {copy.openingDateLabel}
          <span className="ml-1.5 font-normal text-ink/40 dark:text-fog/40">{copy.openingDateHint}</span>
        </label>
        <input
          type="date"
          value={openingDate}
          onChange={(e) => setOpeningDate(e.target.value)}
          className="w-full max-w-xs rounded-xl border border-ink/[0.08] bg-white px-3 py-2 text-[13px] text-ink outline-none transition focus:border-deep-violet/30 dark:border-fog/[0.1] dark:bg-ink dark:text-fog"
        />
      </div>
      <div className="pt-2 sm:flex sm:justify-end">
        <button onClick={handleSave} disabled={saving} className="btn-primary disabled:opacity-50">
          {saving
            ? copy.saving
            : bulk
              ? copy.applyToBranches.replace("{count}", String(bulk.branches.length))
              : copy.saveDescription}
        </button>
      </div>
    </div>
  );
}

function GoogleUpdatesTab({ copy }: { copy: LocationsCopy }) {
  const [updates, setUpdates] = useState<{ id: string; field: string; current: string; proposed: string; status: string }[]>([]);

  return (
      <div className="space-y-5">
        <SectionTitle title={copy.tabGoogleUpdates} subtitle={copy.googleUpdatesSubtitle} />
        <p className="-mt-2 text-[11px] text-ink/40 dark:text-fog/40">{copy.googleUpdatesHint}</p>
      {updates.length === 0 ? (
        <div className="flex flex-col items-center py-10">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="mb-2 h-8 w-8 text-ink/20 dark:text-fog/20">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14" strokeLinecap="round" />
            <path d="M22 4L12 14.01l-3-3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <p className="text-[13px] text-ink/40 dark:text-fog/40">{copy.googleUpdatesEmpty}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {updates.map((u) => (
            <div key={u.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-ink/[0.06] bg-ink/[0.02] p-3 sm:flex-nowrap sm:gap-4 dark:border-fog/[0.06] dark:bg-fog/[0.02]">
              <div className="min-w-0 flex-1">
                <p className="text-[12px] font-semibold text-ink dark:text-fog">{u.field}</p>
                <p className="text-[11px] text-ink/40 dark:text-fog/40">{copy.currentLabel} {u.current}</p>
                <p className="text-[11px] text-deep-violet">{copy.proposedLabel} {u.proposed}</p>
              </div>
              <button className="rounded-lg bg-emerald-500 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-emerald-600">{copy.accept}</button>
              <button className="rounded-lg border border-ink/[0.1] px-2.5 py-1 text-[11px] font-semibold text-ink/50 hover:bg-ink/[0.04] dark:text-fog/50">{copy.reject}</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Add Location Modal ──────────────────────────── */

/* ── Shared pieces ───────────────────────────────── */

/* Add Location Modal (Google create-location workflow, frontend-first).
   Steps mirror Google's recommended flow: details → duplicate check →
   create → verification. Server calls are stubbed (TODO) until the direct
   Google connection lands. "Save draft" persists to localStorage only. */

const CREATE_DRAFT_KEY = "sayvors.locationDraft.v1";

interface LocationDraft {
  name: string;
  category: string;
  street: string;
  city: string;
  postalCode: string;
  country: string;
  phone: string;
  website: string;
}

const EMPTY_DRAFT: LocationDraft = {
  name: "",
  category: "",
  street: "",
  city: "",
  postalCode: "",
  country: "",
  phone: "",
  website: "",
};

function loadCreateDraft(): LocationDraft {
  try {
    const raw = localStorage.getItem(CREATE_DRAFT_KEY);
    if (!raw) return { ...EMPTY_DRAFT };
    const parsed = JSON.parse(raw) as Partial<LocationDraft>;
    return { ...EMPTY_DRAFT, ...parsed };
  } catch {
    return { ...EMPTY_DRAFT };
  }
}

type VerifyMethod = "auto" | "email" | "sms" | "call" | "postcard";

const VERIFY_METHODS: { key: VerifyMethod; label: string; hint: string }[] = [
  { key: "auto", label: "Automatic", hint: "Google verifies instantly when eligible — nothing to do." },
  { key: "email", label: "Email", hint: "A PIN goes to the business email address." },
  { key: "sms", label: "SMS", hint: "A PIN goes to the business phone by text." },
  { key: "call", label: "Phone call", hint: "Google calls the business phone with a PIN." },
  { key: "postcard", label: "Postcard", hint: "A PIN arrives by mail in several days." },
];

function GroupsModal({
  groups,
  locations,
  copy,
  onClose,
  onChanged,
}: {
  groups: LocationGroup[];
  locations: LocationOption[];
  copy: LocationsCopy;
  onClose: () => void;
  onChanged: (next: LocationGroup[]) => void;
}) {
  const [name, setName] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const editing = editingId ? groups.find((g) => g.id === editingId) ?? null : null;

  const startEdit = (g: LocationGroup) => {
    setEditingId(g.id);
    setName(g.name);
    setPicked(g.listing_ids);
    setError(null);
  };

  const reset = () => {
    setEditingId(null);
    setName("");
    setPicked([]);
    setError(null);
  };

  const toggle = (id: string) =>
    setPicked((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  /* Group members that are no longer connected still show as checked-but-
     missing rather than vanishing, so an accidental disconnect doesn't
     silently rewrite somebody's group. */
  const missingIds = editing
    ? editing.listing_ids.filter((id) => !locations.some((l) => l.id === id))
    : [];

  const save = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (picked.length === 0) {
      setError(copy.groupNeedsLocations);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = editingId
        ? await apiFetch(`/api/v1/locations/groups/${editingId}`, {
            method: "PATCH",
            body: JSON.stringify({ name: trimmed, listing_ids: picked }),
          })
        : await apiFetch("/api/v1/locations/groups", {
            method: "POST",
            body: JSON.stringify({ name: trimmed, listing_ids: picked }),
          });
      onChanged(editingId ? groups.map((g) => (g.id === editingId ? (next as LocationGroup) : g)) : [...groups, next as LocationGroup]);
      reset();
    } catch (e) {
      const detail = e instanceof Error ? e.message : "";
      setError(/already have a group/i.test(detail) ? copy.groupNameTaken : detail || copy.groupNameTaken);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (g: LocationGroup) => {
    if (!window.confirm(copy.groupDeleteConfirm)) return;
    setBusy(true);
    try {
      await apiFetch(`/api/v1/locations/groups/${g.id}`, { method: "DELETE" });
      onChanged(groups.filter((x) => x.id !== g.id));
      if (editingId === g.id) reset();
    } catch (e) {
      setError(e instanceof Error ? e.message : "");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-[2px]" role="presentation" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={copy.manageGroupsTitle}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink"
      >
        <div className="flex items-start justify-between gap-3">
          <SectionTitle title={copy.manageGroupsTitle} subtitle={copy.manageGroupsSubtitle} />
          <button onClick={onClose} aria-label="Close" className="rounded-lg px-2 py-1 text-[16px] font-bold text-ink/40 transition hover:bg-ink/[0.04] dark:text-fog/40">
            ×
          </button>
        </div>

        {groups.length > 0 && (
          <ul className="mb-4 space-y-1.5">
            {groups.map((g) => {
              const live = g.listing_ids.filter((id) => locations.some((l) => l.id === id));
              return (
                <li key={g.id} className="flex items-center gap-2 rounded-xl border border-ink/[0.06] px-3 py-2 dark:border-fog/[0.06]">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-semibold text-ink dark:text-fog">{g.name}</p>
                    <p className="text-[11px] text-ink/45 dark:text-fog/45">
                      {live.length === 0 ? copy.groupEmpty : `${live.length} · ${live.map((id) => locations.find((l) => l.id === id)?.name ?? id).join(", ")}`}
                    </p>
                  </div>
                  <button onClick={() => startEdit(g)} className="rounded-lg px-2 py-1 text-[12px] font-semibold text-ink/55 transition hover:bg-ink/[0.04] dark:text-fog/55">
                    {copy.groupEdit}
                  </button>
                  <button onClick={() => remove(g)} disabled={busy} className="rounded-lg px-2 py-1 text-[12px] font-semibold text-red-600 transition hover:bg-red-50 disabled:opacity-40 dark:text-red-400">
                    {copy.groupDelete}
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <div className="space-y-3 border-t border-ink/[0.06] pt-4 dark:border-fog/[0.06]">
          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink/60 dark:text-fog/60">{copy.groupName}</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={copy.groupNamePlaceholder}
              className="input-field w-full"
            />
          </label>

          <div>
            <p className="mb-1.5 text-[12px] font-medium text-ink/60 dark:text-fog/60">{copy.groupLocations}</p>
            {locations.length === 0 ? (
              <p className="text-[12px] text-ink/45 dark:text-fog/45">{copy.groupNoLocationsYet}</p>
            ) : (
              <ul className="max-h-56 space-y-1 overflow-y-auto rounded-xl border border-ink/[0.06] p-2 dark:border-fog/[0.06]">
                {locations.map((l) => (
                  <li key={l.id}>
                    <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-1.5 transition hover:bg-ink/[0.03] dark:hover:bg-fog/[0.04]">
                      <input
                        type="checkbox"
                        checked={picked.includes(l.id)}
                        onChange={() => toggle(l.id)}
                        className="h-4 w-4 accent-deep-violet"
                      />
                      <span className="min-w-0 flex-1 truncate text-[13px] text-ink dark:text-fog">{l.name}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
            {missingIds.length > 0 && (
              <p className="mt-1.5 text-[11px] text-amber-600 dark:text-amber-400">
                {missingIds.length} no longer connected
              </p>
            )}
          </div>

          {error && <p className="text-[12px] font-medium text-red-600 dark:text-red-400">{error}</p>}

          <div className="flex items-center gap-2 pt-1">
            <button onClick={save} disabled={busy} className="btn-primary disabled:opacity-50">
              {editing ? copy.groupSave : copy.newGroup}
            </button>
            {editing && (
              <button onClick={reset} className="rounded-xl px-3 py-2 text-[12px] font-semibold text-ink/55 transition hover:bg-ink/[0.04] dark:text-fog/55">
                {copy.groupCancel}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function AddLocationModal({ onClose, onSaved }: { onClose: () => void; onSaved: (text: string) => void }) {
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState<LocationDraft>(() => loadCreateDraft());
  const [errors, setErrors] = useState<string[]>([]);
  const [checked, setChecked] = useState(false);
  const [method, setMethod] = useState<VerifyMethod>("auto");
  const [pin, setPin] = useState("");
  const [saving, setSaving] = useState(false);

  const steps = ["Details", "Matches", "Review", "Verification"];

  const nextFromDetails = () => {
    const missing: string[] = [];
    if (!draft.name.trim()) missing.push("Business name");
    if (!draft.category.trim()) missing.push("Primary category");
    if (!draft.country.trim()) missing.push("Country");
    if (missing.length) {
      setErrors(missing);
      return;
    }
    setErrors([]);
    setStep(2);
  };

  // TODO: POST /api/v1/locations/check — GoogleLocations duplicate matches.
  // Runs for real once Google is connected; until then it only marks the
  // step reviewed so the draft can be completed.
  const runDuplicateCheck = () => {
    setChecked(true);
  };

  const saveDraft = () => {
    setSaving(true);
    try {
      localStorage.setItem(CREATE_DRAFT_KEY, JSON.stringify(draft));
    } catch {
      /* private mode — draft stays in memory for this session */
    } finally {
      setSaving(false);
    }
    onSaved("Draft saved — it'll pre-fill Create when Google is connected.");
  };

  // TODO: POST /api/v1/locations — accounts.locations.create (validateOnly first).
  // TODO: POST /api/v1/locations/{id}/verification-options → verify → complete.

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4 backdrop-blur-[2px]" role="presentation" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Add location"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-2xl border border-ink/[0.06] bg-white p-5 dark:border-fog/[0.06] dark:bg-ink"
      >
        <div className="flex items-start justify-between gap-3">
          <SectionTitle title="Add location" subtitle="Create a new Google business location. Saved as a draft until Google is connected." />
          <button onClick={onClose} aria-label="Close" className="rounded-lg px-2 py-1 text-[16px] font-bold text-ink/40 transition hover:bg-ink/[0.04] dark:text-fog/40">
            ×
          </button>
        </div>

        {/* Step indicator */}
        <ol className="mb-4 flex items-center gap-1.5">
          {steps.map((label, i) => {
            const n = i + 1;
            const active = n === step;
            const done = n < step;
            return (
              <li key={label} className="flex flex-1 items-center gap-1.5">
                <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${done ? "bg-emerald-500 text-white" : active ? "bg-deep-violet text-white" : "bg-ink/[0.08] text-ink/40 dark:bg-fog/[0.08] dark:text-fog/40"}`}>
                  {done ? "✓" : n}
                </span>
                <span className={`text-[11px] font-semibold ${active ? "text-deep-violet" : "text-ink/40 dark:text-fog/40"}`}>{label}</span>
                {n < steps.length && <span className="h-px flex-1 bg-ink/[0.08] dark:bg-fog/[0.08]" aria-hidden />}
              </li>
            );
          })}
        </ol>

        {step === 1 && (
          <div className="space-y-4">
            {errors.length > 0 && (
              <p className="rounded-xl border border-red-200 bg-red-50 p-3 text-[12px] text-red-700">
                Required: {errors.join(", ")}.
              </p>
            )}
            <Field label="Business name *">
              <input value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder="Sayvors Company" className="input-field" />
            </Field>
            <Field label="Primary category *">
              <input value={draft.category} onChange={(e) => setDraft((d) => ({ ...d, category: e.target.value }))} placeholder="e.g. Software company" className="input-field" />
            </Field>
            <Field label="Street address">
              <input value={draft.street} onChange={(e) => setDraft((d) => ({ ...d, street: e.target.value }))} placeholder="Street and number" className="input-field" />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="City">
                <input value={draft.city} onChange={(e) => setDraft((d) => ({ ...d, city: e.target.value }))} placeholder="Riyadh" className="input-field" />
              </Field>
              <Field label="Postal code">
                <input value={draft.postalCode} onChange={(e) => setDraft((d) => ({ ...d, postalCode: e.target.value }))} placeholder="12213" className="input-field" />
              </Field>
              <Field label="Country *">
                <input value={draft.country} onChange={(e) => setDraft((d) => ({ ...d, country: e.target.value }))} placeholder="SA" className="input-field" />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Phone">
                <input value={draft.phone} onChange={(e) => setDraft((d) => ({ ...d, phone: e.target.value }))} placeholder="+966 55 000 0000" className="input-field" />
              </Field>
              <Field label="Website">
                <input value={draft.website} onChange={(e) => setDraft((d) => ({ ...d, website: e.target.value }))} placeholder="https://..." className="input-field" />
              </Field>
            </div>
            <div className="flex justify-end gap-2 pt-1">
              <button onClick={onClose} className="btn-secondary">Cancel</button>
              <button onClick={nextFromDetails} className="btn-primary">Continue →</button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <p className="text-[12px] leading-relaxed text-ink/60 dark:text-fog/60">
              Before creating, Google must be checked for an existing or claimed listing at this address — creating a duplicate can get the listing suspended.
            </p>
            {!checked ? (
              <button onClick={runDuplicateCheck} className="btn-secondary w-full">
                Check Google for existing matches
              </button>
            ) : (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-[12px] text-amber-800">
                Live duplicate check runs against Google once connected — no live check yet. Your details are kept; you can continue and save the draft.
              </div>
            )}
            <div className="flex justify-between gap-2 pt-1">
              <button onClick={() => setStep(1)} className="btn-secondary">← Back</button>
              <button onClick={() => setStep(3)} className="btn-primary">Continue →</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <dl className="space-y-1.5 rounded-xl bg-ink/[0.03] p-4 text-[12px] dark:bg-fog/[0.04]">
              {[
                ["Business name", draft.name || "—"],
                ["Category", draft.category || "—"],
                ["Address", [draft.street, draft.city, draft.postalCode, draft.country].filter(Boolean).join(", ") || "—"],
                ["Phone", draft.phone || "—"],
                ["Website", draft.website || "—"],
              ].map(([k, v]) => (
                <div key={k} className="flex gap-3">
                  <dt className="w-28 shrink-0 font-medium text-ink/50 dark:text-fog/50">{k}</dt>
                  <dd className="font-semibold text-ink dark:text-fog">{v}</dd>
                </div>
              ))}
            </dl>
            <button onClick={saveDraft} disabled={saving} className="btn-primary w-full disabled:opacity-50">
              {saving ? "Saving..." : "Save draft"}
            </button>
            <button disabled title="Available once Google is connected" className="btn-secondary w-full cursor-not-allowed opacity-50">
              Create on Google (needs connection)
            </button>
            <div className="flex justify-start pt-1">
              <button onClick={() => setStep(2)} className="btn-secondary">← Back</button>
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-4">
            <p className="text-[12px] leading-relaxed text-ink/60 dark:text-fog/60">
              New locations stay invisible on Maps and Search until the owner verifies them. Pick how verification will run once the listing is created.
            </p>
            <div className="space-y-2">
              {VERIFY_METHODS.map((m) => (
                <label key={m.key} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3 transition ${method === m.key ? "border-deep-violet/40 bg-deep-violet/[0.04]" : "border-ink/[0.08] dark:border-fog/[0.08]"}`}>
                  <input
                    type="radio"
                    name="verify-method"
                    checked={method === m.key}
                    onChange={() => setMethod(m.key)}
                    className="mt-0.5 accent-deep-violet"
                  />
                  <span>
                    <span className="block text-[13px] font-semibold text-ink dark:text-fog">{m.label}</span>
                    <span className="block text-[11px] text-ink/45 dark:text-fog/45">{m.hint}</span>
                  </span>
                </label>
              ))}
            </div>
            <Field label="Verification PIN (preview — enter the code Google sends)">
              <input value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" placeholder="6-digit code" className="input-field" />
            </Field>
            <button disabled title="Available once Google is connected" className="btn-secondary w-full cursor-not-allowed opacity-50">
              Complete verification (needs connection)
            </button>
            <div className="flex justify-between gap-2 pt-1">
              <button onClick={() => setStep(3)} className="btn-secondary">← Back</button>
              <button onClick={onClose} className="btn-primary">Done</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SectionTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="mb-1">
      <h3 className="text-[14px] font-semibold text-ink dark:text-fog">{title}</h3>
      <p className="text-[12px] text-ink/40 dark:text-fog/40">{subtitle}</p>
    </div>
  );
}

function Field({ label, children, varies }: { label: string; children: React.ReactNode; varies?: boolean }) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-medium text-ink/60 dark:text-fog/60">
        {label}
        {varies ? <VariesBadge /> : null}
      </label>
      {children}
    </div>
  );
}

function VariesBadge() {
  return (
    <span
      title="Different values across branches — saving will overwrite all of them"
      className="ml-1.5 inline-flex items-center rounded-full bg-amber-100 px-1.5 py-px align-middle text-[9px] font-bold uppercase tracking-wide text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
    >
      varies
    </span>
  );
}

/**
 * The value each branch currently holds, listed under the input in
 * "All branches" mode. The inputs start blank there (no single profile to
 * prefill from), so this is the only place the merchant can see what is
 * actually set per branch — and, after a save, proof it landed.
 */
function BranchValues({
  branches,
  values,
  missingLabel,
}: {
  branches: { id: string; name: string }[];
  values: Record<string, string>;
  missingLabel: string;
}) {
  if (branches.length < 2) return null;
  return (
    <ul className="mt-1.5 space-y-0.5 rounded-lg bg-ink/[0.03] p-2 dark:bg-fog/[0.04]">
      {branches.map((b) => {
        const v = (values[b.id] ?? "").trim();
        return (
          <li key={b.id} className="flex items-baseline gap-2 text-[11px] leading-snug">
            <span className="min-w-0 flex-1 truncate text-ink/50 dark:text-fog/50">
              {b.name}
            </span>
            <span
              className={`shrink-0 tabular-nums ${v ? "font-medium text-ink/70 dark:text-fog/70" : "italic text-ink/30 dark:text-fog/30"}`}
              dir="ltr"
            >
              {v || missingLabel}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function describeHours(
  regular: Record<string, { open: string; close: string; closed: boolean }>,
  copy: LocationsCopy
): string[] {
  const open = Object.entries(regular).filter(([, v]) => !v.closed);
  if (open.length === 0) return [copy.hoursAllClosed];
  const days = open
    .map(([d, v]) => `${dayLabel(d, copy)} ${v.open || "?"}–${v.close || "?"}`)
    .join(", ");
  return [copy.hoursSummary.replace("{days}", days)];
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center py-10">
      <p className="text-[13px] text-ink/40 dark:text-fog/40">Select a location to manage.</p>
    </div>
  );
}

function LocationIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className={className}>
      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

