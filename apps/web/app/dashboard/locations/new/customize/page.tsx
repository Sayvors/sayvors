"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import LogoLoader from "@/components/LogoLoader";
import { apiFetch } from "@/lib/api-rag";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const STEPS = ["Hours", "Description", "Photos", "Done"] as const;

interface DayHours {
  open: string;
  close: string;
  closed: boolean;
  all_day?: boolean;
}

interface Profile {
  listing_id: string;
  name: string;
  address: string | null;
  description: string | null;
  hours: {
    regular?: Record<string, DayHours>;
    special?: unknown[];
    more?: unknown[];
  };
}

function blankHours(): Record<string, DayHours> {
  return Object.fromEntries(
    DAYS.map((day) => [day, { open: "09:00", close: "17:00", closed: true }]),
  );
}

export default function CustomizeLocationPage() {
  const searchParams = useSearchParams();
  const channel = searchParams.get("channel") ?? "";
  const listing = searchParams.get("listing") ?? "";

  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [hours, setHours] = useState<Record<string, DayHours>>(blankHours);
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState<"profile" | "gallery" | null>(null);
  const [uploaded, setUploaded] = useState<string[]>([]);
  const initialized = useRef(false);

  useEffect(() => {
    if (!listing) {
      setLoading(false);
      setLoadError("This page needs a location. Open it from the create-location flow.");
      return;
    }
    let cancelled = false;
    apiFetch(`/api/v1/locations/${encodeURIComponent(listing)}`)
      .then((data) => {
        if (cancelled) return;
        const next = data as Profile;
        setProfile(next);
        if (!initialized.current) {
          setHours({ ...blankHours(), ...(next.hours?.regular ?? {}) });
          setDescription(next.description ?? "");
          initialized.current = true;
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : "Could not load this location.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [listing]);

  const save = async (body: Record<string, unknown>, note: string) => {
    if (!listing) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const next = (await apiFetch(`/api/v1/locations/${encodeURIComponent(listing)}`, {
        method: "PUT",
        body: JSON.stringify(body),
      })) as Profile;
      setProfile(next);
      setMessage(note);
      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this change.");
      return false;
    } finally {
      setSaving(false);
    }
  };

  const updateDay = (day: string, patch: Partial<DayHours>) => {
    setHours((current) => ({
      ...current,
      [day]: { ...current[day], ...patch, ...(patch.open || patch.close ? { all_day: false } : {}) },
    }));
  };

  const saveHours = async () => {
    const ok = await save({ hours: { regular: hours } }, "Business hours saved.");
    if (ok) setStep(1);
  };

  const saveDescription = async () => {
    const ok = await save({ description }, "Business description saved.");
    if (ok) setStep(2);
  };

  const uploadPhoto = async (file: File, method: "profile" | "gallery") => {
    if (!listing) return;
    setUploading(method);
    setError(null);
    setMessage(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const uploadedFile = (await apiFetch("/api/v1/media/upload", {
        method: "POST",
        body: form,
      })) as { image_url?: string };
      if (!uploadedFile.image_url) throw new Error("The upload did not return an image URL.");
      await apiFetch("/api/v1/media/", {
        method: "POST",
        body: JSON.stringify({
          listing_id: listing,
          image_url: uploadedFile.image_url,
          type: "PHOTO",
          category: method === "profile" ? "EXTERIOR" : "ADDITIONAL",
          caption: method === "profile" ? "Storefront" : "Business photo",
          action: "publish",
          publish_method: method,
        }),
      });
      setUploaded((current) => [...current, `${method === "profile" ? "Storefront" : "Business photo"}: ${file.name}`]);
      setMessage(
        method === "profile"
          ? "Storefront photo uploaded. It becomes visible after verification."
          : "Business photo uploaded. It becomes visible after verification.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not upload this photo.");
    } finally {
      setUploading(null);
    }
  };

  if (!listing) {
    return (
      <div className="mx-auto w-full max-w-2xl p-4 sm:p-8">
        <div className="rounded-2xl border border-ink/[0.06] bg-white p-6 shadow-sm dark:border-fog/[0.08] dark:bg-ink">
          <h1 className="text-[20px] font-bold text-ink dark:text-fog">Location not found</h1>
          <p className="mt-2 text-[13px] text-ink/60 dark:text-fog/60">{loadError}</p>
          <Link href="/dashboard/locations" className="btn-primary mt-5 inline-flex">
            Back to locations
          </Link>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <LogoLoader size={30} />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="mx-auto w-full max-w-2xl p-4 sm:p-8">
        <div className="rounded-2xl border border-red-200 bg-red-50 p-5 text-[13px] text-red-700 dark:border-red-500/25 dark:bg-red-500/10 dark:text-red-200">
          {loadError}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-5xl p-3 sm:p-6">
      <div className="grid gap-5 lg:grid-cols-[230px_minmax(0,1fr)]">
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <Link
            href="/dashboard/locations"
            className="inline-flex text-[12px] font-semibold text-ink/50 transition hover:text-ink dark:text-fog/50 dark:hover:text-fog"
          >
            ← Locations
          </Link>
          <h1 className="mt-3 text-[21px] font-bold tracking-tight text-ink dark:text-fog">
            Customize profile
          </h1>
          <p className="mt-1 text-[11.5px] leading-relaxed text-ink/50 dark:text-fog/50">
            {profile?.name ?? "Your location"}
          </p>
          <ol className="mt-5 space-y-3">
            {STEPS.map((label, index) => {
              const done = index < step;
              const active = index === step;
              return (
                <li key={label} className="flex items-center gap-2.5">
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
                  <span
                    className={`text-[12px] font-semibold ${
                      active
                        ? "text-ink dark:text-fog"
                        : done
                          ? "text-ink/65 dark:text-fog/65"
                          : "text-ink/40 dark:text-fog/40"
                    }`}
                  >
                    {label}
                  </span>
                </li>
              );
            })}
          </ol>
          <div className="mt-6 rounded-xl border border-ink/[0.06] bg-white p-3 text-[11px] leading-relaxed text-ink/50 dark:border-fog/[0.08] dark:bg-ink dark:text-fog/50">
            Google shows these edits once the location is verified. You can skip any step and come
            back from Locations.
          </div>
        </aside>

        <main className="min-w-0">
          <div className="rounded-2xl border border-ink/[0.06] bg-white p-5 shadow-sm sm:p-7 dark:border-fog/[0.08] dark:bg-ink">
            {message && (
              <p className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-[12px] text-emerald-700 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-200">
                {message}
              </p>
            )}
            {error && (
              <p role="alert" className="mb-4 rounded-xl border border-red-200 bg-red-50 p-3 text-[12px] text-red-700 dark:border-red-500/25 dark:bg-red-500/10 dark:text-red-200">
                {error}
              </p>
            )}

            {step === 0 && (
              <div className="space-y-4">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-deep-violet">
                    Step 1 of {STEPS.length}
                  </p>
                  <h2 className="text-[20px] font-bold text-ink dark:text-fog">Add business hours</h2>
                  <p className="mt-1 text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
                    Let customers know when you are open. Closed days are hidden from Google.
                  </p>
                </div>
                <div className="space-y-2">
                  {DAYS.map((day) => {
                    const value = hours[day] ?? { open: "09:00", close: "17:00", closed: true };
                    return (
                      <div
                        key={day}
                        className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-3 dark:border-fog/[0.08] dark:bg-fog/[0.03]"
                      >
                        <label className="flex w-32 shrink-0 items-center gap-2">
                          <input
                            type="checkbox"
                            checked={!value.closed}
                            onChange={(event) =>
                              updateDay(day, { closed: !event.target.checked })
                            }
                            className="h-4 w-4 rounded border-ink/20 text-deep-violet focus:ring-deep-violet/40"
                          />
                          <span className="text-[12.5px] font-semibold text-ink dark:text-fog">
                            {day}
                          </span>
                        </label>
                        {value.closed ? (
                          <span className="text-[11.5px] text-ink/35 dark:text-fog/35">Closed</span>
                        ) : (
                          <div className="flex flex-wrap items-center gap-2">
                            <input
                              type="time"
                              value={value.open}
                              onChange={(event) => updateDay(day, { open: event.target.value })}
                              className="input-field w-32"
                              aria-label={`${day} opening time`}
                            />
                            <span className="text-[11px] text-ink/35">to</span>
                            <input
                              type="time"
                              value={value.close}
                              onChange={(event) => updateDay(day, { close: event.target.value })}
                              className="input-field w-32"
                              aria-label={`${day} closing time`}
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
                <div className="flex flex-wrap items-center gap-2 border-t border-ink/[0.06] pt-4 dark:border-fog/[0.08]">
                  <button type="button" onClick={() => setStep(1)} className="btn-secondary">
                    Skip
                  </button>
                  <button type="button" onClick={() => void saveHours()} disabled={saving} className="btn-primary disabled:opacity-50">
                    {saving ? "Saving..." : "Save & continue"}
                  </button>
                </div>
              </div>
            )}

            {step === 1 && (
              <div className="space-y-4">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-deep-violet">
                    Step 2 of {STEPS.length}
                  </p>
                  <h2 className="text-[20px] font-bold text-ink dark:text-fog">
                    Add business description
                  </h2>
                  <p className="mt-1 text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
                    Tell customers what you offer. Google gives you up to 750 characters.
                  </p>
                </div>
                <div>
                  <textarea
                    value={description}
                    onChange={(event) => setDescription(event.target.value.slice(0, 750))}
                    rows={8}
                    placeholder="What does your business do? What makes it different?"
                    className="input-field resize-y"
                  />
                  <p className="mt-1 text-right text-[10.5px] text-ink/35 dark:text-fog/35">
                    {description.length}/750
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2 border-t border-ink/[0.06] pt-4 dark:border-fog/[0.08]">
                  <button type="button" onClick={() => setStep(2)} className="btn-secondary">
                    Skip
                  </button>
                  <button type="button" onClick={() => void saveDescription()} disabled={saving} className="btn-primary disabled:opacity-50">
                    {saving ? "Saving..." : "Save & continue"}
                  </button>
                </div>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-5">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-deep-violet">
                    Step 3 of {STEPS.length}
                  </p>
                  <h2 className="text-[20px] font-bold text-ink dark:text-fog">Add photos</h2>
                  <p className="mt-1 text-[12px] leading-relaxed text-ink/55 dark:text-fog/55">
                    A storefront photo helps customers recognise you. Add product or interior
                    photos to show what you do.
                  </p>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="rounded-xl border border-dashed border-ink/15 p-4 text-center transition hover:bg-ink/[0.02] dark:border-fog/15 dark:hover:bg-fog/[0.03]">
                    <span className="block text-[12.5px] font-semibold text-ink dark:text-fog">
                      Storefront photo
                    </span>
                    <span className="mt-0.5 block text-[10.5px] text-ink/45 dark:text-fog/45">
                      The exterior customers see from the street
                    </span>
                    <input
                      type="file"
                      accept="image/*"
                      className="mt-3 block w-full text-[11px]"
                      disabled={uploading !== null}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.currentTarget.value = "";
                        if (file) void uploadPhoto(file, "profile");
                      }}
                    />
                  </label>
                  <label className="rounded-xl border border-dashed border-ink/15 p-4 text-center transition hover:bg-ink/[0.02] dark:border-fog/15 dark:hover:bg-fog/[0.03]">
                    <span className="block text-[12.5px] font-semibold text-ink dark:text-fog">
                      Business photos
                    </span>
                    <span className="mt-0.5 block text-[10.5px] text-ink/45 dark:text-fog/45">
                      Interior, products or team photos
                    </span>
                    <input
                      type="file"
                      accept="image/*"
                      multiple
                      className="mt-3 block w-full text-[11px]"
                      disabled={uploading !== null}
                      onChange={(event) => {
                        const files = Array.from(event.target.files ?? []);
                        event.currentTarget.value = "";
                        for (const file of files.slice(0, 5)) void uploadPhoto(file, "gallery");
                      }}
                    />
                  </label>
                </div>

                {uploading && (
                  <p className="text-[11.5px] text-ink/50 dark:text-fog/50">Uploading photo...</p>
                )}
                {uploaded.length > 0 && (
                  <ul className="space-y-1 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-[11.5px] text-emerald-800 dark:border-emerald-500/25 dark:bg-emerald-500/10 dark:text-emerald-200">
                    {uploaded.map((item) => (
                      <li key={item}>✓ {item}</li>
                    ))}
                  </ul>
                )}

                <div className="flex flex-wrap items-center gap-2 border-t border-ink/[0.06] pt-4 dark:border-fog/[0.08]">
                  <button type="button" onClick={() => setStep(3)} className="btn-secondary">
                    Skip
                  </button>
                  <button type="button" onClick={() => setStep(3)} disabled={uploading !== null} className="btn-primary disabled:opacity-50">
                    Continue
                  </button>
                </div>
              </div>
            )}

            {step === 3 && (
              <div className="space-y-5">
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-deep-violet">
                    Step 4 of {STEPS.length}
                  </p>
                  <h2 className="text-[20px] font-bold text-ink dark:text-fog">
                    Your edits will be visible once you&apos;re verified
                  </h2>
                  <p className="mt-2 text-[12.5px] leading-relaxed text-ink/55 dark:text-fog/55">
                    You can continue to make updates at any time. All edits become visible to
                    customers on Google once the location is verified.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link href="/dashboard/locations" className="btn-primary">
                    Continue to locations
                  </Link>
                  {channel && (
                    <Link
                      href={`/dashboard/verification?channel=${encodeURIComponent(channel)}`}
                      className="btn-secondary"
                    >
                      Open verification
                    </Link>
                  )}
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
