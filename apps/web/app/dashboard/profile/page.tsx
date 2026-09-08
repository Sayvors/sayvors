"use client";

import { useCallback, useEffect, useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import ProfileHeader from "@/components/profile/ProfileHeader";
import ProfileAbout from "@/components/profile/ProfileAbout";
import ProfileAccount from "@/components/profile/ProfileAccount";
import ProfileLimits from "@/components/profile/ProfileLimits";
import ProfilePreferences from "@/components/profile/ProfilePreferences";
import LogoLoader from "@/components/LogoLoader";
import {
  getProfile,
  getUsage,
  updatePreferences,
  updateProfile,
  type Profile,
  type UsageItem,
} from "@/lib/api-profile";

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [usage, setUsage] = useState<UsageItem[]>([]);
  const [usageCached, setUsageCached] = useState(false);
  const [loading, setLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function notify(message: string) {
    setToast(message);
    window.setTimeout(() => setToast((t) => (t === message ? null : t)), 3200);
  }

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [p, u] = await Promise.all([
        getProfile(),
        getUsage().catch(() => ({ items: [], cached: false })),
      ]);
      setProfile(p);
      setUsage(u.items ?? []);
      setUsageCached(!!u.cached);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load profile.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load from API on mount
    loadAll();
  }, [loadAll]);

  async function refreshUsage() {
    setUsageLoading(true);
    try {
      const u = await getUsage();
      setUsage(u.items ?? []);
      setUsageCached(!!u.cached);
    } catch (e) {
      notify(e instanceof Error ? e.message : "Could not refresh usage.");
    } finally {
      setUsageLoading(false);
    }
  }

  async function handleAboutSave(data: { bio: string; business_name: string }) {
    setSaving(true);
    try {
      const next = await updateProfile(data);
      setProfile(next);
      notify("About section saved.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAccountSave(data: { first_name: string; last_name: string; phone: string }) {
    setSaving(true);
    try {
      const next = await updateProfile(data);
      setProfile(next);
      notify("Account details saved.");
    } finally {
      setSaving(false);
    }
  }

  async function handlePreferences(theme: string, language: string) {
    setSaving(true);
    try {
      const next = await updatePreferences(theme, language);
      setProfile(next);
      notify("Preferences saved.");
    } catch (e) {
      notify(e instanceof Error ? e.message : "Could not save preferences.");
      throw e;
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="h-full overflow-y-auto bg-[#f3f0ff]">
        <div className="flex min-h-[60vh] items-center justify-center p-6">
          <LogoLoader size={56} label="Loading profile…" showText />
        </div>
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="h-full overflow-y-auto bg-[#f3f0ff]">
        <div className="mx-auto max-w-2xl p-6">
          <div role="alert" className="rounded-2xl border border-coral/30 bg-white p-6 text-center shadow-sm">
            <h1 className="text-[16px] font-bold text-ink">Could not load profile</h1>
            <p className="mt-1 break-words text-[12px] text-ink/60">{error ?? "Unknown error."}</p>
            <button
              onClick={loadAll}
              className="mt-4 rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-bold text-white hover:bg-deep-violet/90"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  const profileFields = [profile.first_name, profile.last_name, profile.email, profile.business_name, profile.phone, profile.bio];
  const completedFields = profileFields.filter((value) => Boolean(value?.trim())).length;
  const profileCompletion = Math.round((completedFields / profileFields.length) * 100);
  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Profile" }]} />
            <h1 className="mt-2 text-[24px] font-black tracking-tight text-ink sm:text-[28px]">Your profile</h1>
            <p className="mt-0.5 text-[12px] text-ink/60 sm:text-[13px]">
              Keep your Sayvors workspace identity, preferences, and account settings in one place.
            </p>
          </div>
          <button
            onClick={loadAll}
            className="rounded-xl border border-ink/10 bg-white px-4 py-2 text-[12px] font-bold text-ink/65 shadow-sm transition hover:border-deep-violet/40 hover:text-deep-violet"
          >
            Refresh data
          </button>
        </div>

        <div className="space-y-5">
          <div className="space-y-4">
            <ProfileHeader profile={profile} onEdit={() => document.getElementById("profile-account")?.scrollIntoView({ behavior: "smooth", block: "start" })} />
            <section className="rounded-2xl border border-white bg-white/80 p-4 shadow-[0_10px_26px_rgba(58,39,120,0.06)]">
              <div className="flex items-center justify-between"><span className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink/45">Profile strength</span><strong className="text-[14px] text-deep-violet">{profileCompletion}%</strong></div>
              <div className="mt-3 h-2 overflow-hidden rounded-full bg-deep-violet/10"><div className="h-full rounded-full bg-gradient-to-r from-deep-violet via-magenta to-coral transition-all" style={{ width: `${profileCompletion}%` }} /></div>
              <p className="mt-2 text-[11px] leading-relaxed text-ink/45">Add your business and phone details to make your workspace easier to recognize.</p>
            </section>
          </div>

          <main className="min-w-0 space-y-5">
            <ProfileAbout
              bio={profile.bio}
              businessName={profile.business_name}
              saving={saving}
              onSave={handleAboutSave}
            />
            <div id="profile-account">
              <ProfileAccount profile={profile} saving={saving} onSave={handleAccountSave} />
            </div>
            <ProfilePreferences
              theme={profile.theme}
              language={profile.language}
              saving={saving}
              onSave={handlePreferences}
            />
            <ProfileLimits items={usage} cached={usageCached} loading={usageLoading} onRefresh={refreshUsage} />

          </main>
        </div>

        {toast && (
          <div
            role="status"
            className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-full bg-ink px-4 py-2 text-[12px] font-semibold text-white shadow-lg"
          >
            {toast}
          </div>
        )}
      </div>
    </div>
  );
}
