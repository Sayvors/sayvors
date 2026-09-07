"use client";

import { useCallback, useEffect, useState } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import ProfileHeader from "@/components/profile/ProfileHeader";
import ProfileAbout from "@/components/profile/ProfileAbout";
import ProfileAccount from "@/components/profile/ProfileAccount";
import ProfileLimits from "@/components/profile/ProfileLimits";
import ProfilePreferences from "@/components/profile/ProfilePreferences";
import ProfileSupport from "@/components/profile/ProfileSupport";
import ProfileRatings from "@/components/profile/ProfileRatings";
import LogoLoader from "@/components/LogoLoader";
import {
  getProfile,
  getSessions,
  getUsage,
  submitFeedback,
  updatePreferences,
  updateProfile,
  type Profile,
  type Session,
  type UsageItem,
} from "@/lib/api-profile";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "account", label: "Account" },
  { id: "preferences", label: "Preferences" },
  { id: "usage", label: "Usage" },
  { id: "feedback", label: "Feedback" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [usage, setUsage] = useState<UsageItem[]>([]);
  const [usageCached, setUsageCached] = useState(false);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [tab, setTab] = useState<TabId>("overview");
  const [loading, setLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [ratingKey, setRatingKey] = useState<string | null>(null);
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
      const [p, u, s] = await Promise.all([
        getProfile(),
        getUsage().catch(() => ({ items: [], cached: false })),
        getSessions().catch(() => ({ sessions: [] })),
      ]);
      setProfile(p);
      setUsage(u.items ?? []);
      setUsageCached(!!u.cached);
      setSessions(s.sessions ?? []);
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

  async function handleRate(category: string, stars: number) {
    setRatingKey(category);
    try {
      const res = await submitFeedback(category, stars);
      setProfile((p) => (p ? { ...p, feedback: res.feedback } : p));
      notify("Thanks for the feedback.");
    } finally {
      setRatingKey(null);
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

  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="mx-auto max-w-6xl space-y-5 p-4 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <Breadcrumbs items={[{ label: "Dashboard", href: "/dashboard" }, { label: "Profile" }]} />
            <h1 className="mt-1 text-[20px] font-bold text-ink sm:text-[22px]">Profile</h1>
            <p className="mt-0.5 text-[12px] text-ink/60 sm:text-[13px]">
              Identity, preferences, usage, and feedback — saved to your account, cached in Redis, and published to Kafka.
            </p>
          </div>
          <button
            onClick={loadAll}
            className="rounded-lg border border-ink/15 bg-white px-3 py-1.5 text-[12px] font-semibold text-ink/70 shadow-sm transition hover:border-deep-violet/40 hover:text-deep-violet"
          >
            Refresh
          </button>
        </div>

        <div
          role="tablist"
          aria-label="Profile sections"
          className="flex gap-1 overflow-x-auto rounded-xl border border-ink/10 bg-white p-1 shadow-sm"
        >
          {TABS.map((t) => {
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t.id)}
                className={`flex-1 whitespace-nowrap rounded-lg px-3 py-2 text-[12px] font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40 ${
                  active ? "bg-deep-violet text-white shadow" : "text-ink/55 hover:bg-fog hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            );
          })}
        </div>

        <div className="grid items-start gap-5 lg:grid-cols-3">
          <div className="space-y-5 lg:col-span-1">
            <ProfileHeader profile={profile} onEdit={() => setTab("account")} />
            <ProfileSupport sessions={sessions} />
          </div>

          <div className="space-y-5 lg:col-span-2" role="tabpanel">
            {tab === "overview" && (
              <>
                <ProfileAbout
                  bio={profile.bio}
                  businessName={profile.business_name}
                  saving={saving}
                  onSave={handleAboutSave}
                />
                <ProfileLimits items={usage} cached={usageCached} loading={usageLoading} onRefresh={refreshUsage} />
              </>
            )}

            {tab === "account" && (
              <ProfileAccount profile={profile} saving={saving} onSave={handleAccountSave} />
            )}

            {tab === "preferences" && (
              <ProfilePreferences
                theme={profile.theme}
                language={profile.language}
                saving={saving}
                onSave={handlePreferences}
              />
            )}

            {tab === "usage" && (
              <ProfileLimits items={usage} cached={usageCached} loading={usageLoading} onRefresh={refreshUsage} />
            )}

            {tab === "feedback" && (
              <ProfileRatings ratings={profile.feedback ?? {}} savingKey={ratingKey} onRate={handleRate} />
            )}
          </div>
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
