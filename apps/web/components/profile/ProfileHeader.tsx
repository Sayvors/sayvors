"use client";

import { fullName, initialsOf, type Profile } from "@/lib/api-profile";

export default function ProfileHeader({
  profile,
  onEdit,
}: {
  profile: Profile;
  onEdit: () => void;
}) {
  const memberYear = new Date(profile.member_since).getFullYear() || "—";

  return (
    <section
      aria-label="Identity"
      className="overflow-hidden rounded-2xl border border-ink/10 bg-white shadow-sm"
    >
      <div className="h-24 bg-gradient-to-r from-deep-violet via-magenta to-coral" />
      <div className="px-5 pb-5">
        <div className="-mt-10 flex flex-wrap items-end gap-4">
          <div
            aria-hidden
            className="flex h-[72px] w-[72px] shrink-0 items-center justify-center rounded-2xl border-4 border-white bg-deep-violet text-xl font-bold text-white shadow-md"
          >
            {initialsOf(profile)}
          </div>
          <div className="min-w-0 flex-1 pb-0.5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-[17px] font-bold text-ink">{fullName(profile)}</h2>
              {profile.email_verified ? (
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-200">
                  Verified
                </span>
              ) : (
                <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700 ring-1 ring-amber-200">
                  Unverified
                </span>
              )}
            </div>
            <p className="truncate text-[12px] text-ink/55">{profile.email}</p>
          </div>
          <button
            onClick={onEdit}
            className="rounded-lg border border-ink/15 px-3 py-1.5 text-[12px] font-semibold text-ink/70 transition hover:border-deep-violet/40 hover:text-deep-violet focus:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40"
          >
            Edit profile
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span className="rounded-full bg-gradient-to-r from-deep-violet to-magenta px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-white">
            {profile.plan} plan
          </span>
          <span className="text-[11px] text-ink/45">Member since {memberYear}</span>
          {profile.onboarded && (
            <span className="text-[11px] text-ink/45">· Onboarded</span>
          )}
        </div>
      </div>
    </section>
  );
}
