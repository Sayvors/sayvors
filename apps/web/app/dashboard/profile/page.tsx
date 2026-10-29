"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import LogoLoader from "@/components/LogoLoader";
import AccountHero, { type ProfileImageKind } from "@/components/profile/AccountHero";
import AccountForm, { type AccountFormPatch } from "@/components/profile/AccountForm";
import ProfileLimits from "@/components/profile/ProfileLimits";
import ProfilePreferences from "@/components/profile/ProfilePreferences";
import ProfileStrength from "@/components/profile/ProfileStrength";
import { useAuth } from "@/lib/auth-context";
import { useI18n } from "@/lib/i18n/I18nProvider";
import { isLocaleCode } from "@/lib/i18n/locales";
import { profileCompletion } from "@/lib/profile-completion";
import {
  getProfile,
  getUsage,
  removeAvatar,
  removeCover,
  setAvatarSource,
  updatePreferences,
  updateProfile,
  uploadProfileImage,
  type AvatarSource,
  type Profile,
  type UsageItem,
} from "@/lib/api-profile";

export default function ProfilePage() {
  const { setLocale } = useI18n();
  const { refreshAuth } = useAuth();

  const [profile, setProfile] = useState<Profile | null>(null);
  const [usage, setUsage] = useState<UsageItem[]>([]);
  const [usageCached, setUsageCached] = useState(false);
  const [loading, setLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(false);
  const [preferencesSaving, setPreferencesSaving] = useState(false);
  const [imageBusy, setImageBusy] = useState<"avatar" | "cover" | "source" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);

  useEffect(() => {
    return () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    };
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextProfile, nextUsage] = await Promise.all([
        getProfile(),
        getUsage().catch(() => ({ items: [], cached: false })),
      ]);
      setProfile(nextProfile);
      setUsage(nextUsage.items ?? []);
      setUsageCached(Boolean(nextUsage.cached));
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : "Could not load profile.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load from API on mount
    void loadAll();
  }, [loadAll]);

  async function refreshUsage() {
    setUsageLoading(true);
    try {
      const next = await getUsage();
      setUsage(next.items ?? []);
      setUsageCached(Boolean(next.cached));
    } catch (e) {
      notify(e instanceof Error && e.message ? e.message : "Could not refresh usage.");
    } finally {
      setUsageLoading(false);
    }
  }

  async function handleAccountSave(patch: AccountFormPatch): Promise<Profile> {
    const next = await updateProfile(patch);
    setProfile(next);
    notify("Account details saved.");
    // The header renders the same name and photo, so refresh its copy too.
    void refreshAuth();
    return next;
  }

  async function handlePreferences(theme: string, language: string): Promise<void> {
    setPreferencesSaving(true);
    try {
      const next = await updatePreferences(theme, language);
      setProfile(next);
      if (isLocaleCode(language)) setLocale(language, false);
      notify("Preferences saved.");
    } catch (e) {
      notify(e instanceof Error && e.message ? e.message : "Could not save preferences.");
      throw e;
    } finally {
      setPreferencesSaving(false);
    }
  }

  async function handleImage(kind: ProfileImageKind, file: File): Promise<void> {
    setImageBusy(kind);
    try {
      const next = await uploadProfileImage(kind, file);
      setProfile(next);
      notify(kind === "avatar" ? "Profile photo updated." : "Cover image updated.");
      if (kind === "avatar") void refreshAuth();
    } finally {
      setImageBusy(null);
    }
  }

  async function handleSelectSource(source: AvatarSource): Promise<void> {
    setImageBusy("source");
    try {
      const next = await setAvatarSource(source);
      setProfile(next);
      notify("Profile photo switched.");
      void refreshAuth();
    } finally {
      setImageBusy(null);
    }
  }

  async function handleRemoveAvatar(): Promise<void> {
    setImageBusy("source");
    try {
      const next = await removeAvatar();
      setProfile(next);
      notify("Profile photo removed.");
      void refreshAuth();
    } finally {
      setImageBusy(null);
    }
  }

  async function handleRemoveCover(): Promise<void> {
    setImageBusy("cover");
    try {
      const next = await removeCover();
      setProfile(next);
      notify("Cover image removed.");
    } finally {
      setImageBusy(null);
    }
  }

  if (loading) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="flex min-h-[60vh] items-center justify-center p-6">
          <LogoLoader size={56} label="Loading profile…" showText />
        </div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="h-full overflow-y-auto">
        <div className="mx-auto max-w-2xl p-6">
          <div
            role="alert"
            className="rounded-[32px] bg-white p-8 text-center shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)] ring-1 ring-coral/25 dark:bg-[#1b1530]"
          >
            <h1 className="text-[17px] font-black text-ink dark:text-fog">Could not load profile</h1>
            <p className="mt-1 break-words text-[12px] text-ink/55 dark:text-fog/55">
              {error ?? "Unknown error."}
            </p>
            <button
              type="button"
              onClick={() => void loadAll()}
              className="mt-5 rounded-[20px] bg-deep-violet px-5 py-2.5 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 active:translate-y-0.5 active:scale-[0.98]"
            >
              Try again
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 p-4 sm:p-6 lg:p-8">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Account" }]} />
            <h1 className="mt-2 text-[26px] font-black tracking-tight text-ink dark:text-fog sm:text-[30px]">
              Account
            </h1>
            <p className="mt-0.5 max-w-xl text-[12.5px] leading-relaxed text-ink/55 dark:text-fog/55">
              Your photo, personal details and workspace preferences — all in one place.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadAll()}
            className="inline-flex items-center gap-2 rounded-[20px] bg-white px-4 py-2.5 text-[12px] font-bold text-ink/65 shadow-[0_8px_20px_-14px_rgba(61,29,110,0.55)] ring-1 ring-ink/[0.08] transition hover:text-deep-violet focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 active:translate-y-0.5 active:scale-[0.98] dark:bg-[#1b1530] dark:text-fog/65 dark:ring-white/[0.1]"
          >
            <svg
              viewBox="0 0 16 16"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-3.5 w-3.5"
              aria-hidden
            >
              <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
              <path d="M13.5 2.5V5H11" />
            </svg>
            Refresh
          </button>
        </div>

        <AccountHero
          profile={profile}
          completion={profileCompletion(profile)}
          busy={imageBusy}
          onUpload={handleImage}
          onSelectSource={handleSelectSource}
          onRemoveAvatar={handleRemoveAvatar}
          onRemoveCover={handleRemoveCover}
        />

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
          <div className="min-w-0 space-y-5">
            <AccountForm profile={profile} onSave={handleAccountSave} />
            <ProfilePreferences
              theme={profile.theme}
              language={profile.language}
              saving={preferencesSaving}
              onSave={handlePreferences}
            />
          </div>

          <aside className="min-w-0 space-y-5 lg:sticky lg:top-0">
            <ProfileStrength profile={profile} />
            <ProfileLimits
              items={usage}
              cached={usageCached}
              loading={usageLoading}
              onRefresh={() => void refreshUsage()}
            />
          </aside>
        </div>
      </div>

      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-full bg-ink px-4 py-2 text-[12px] font-semibold text-white shadow-lg"
        >
          {toast}
        </div>
      )}
    </div>
  );
}
