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
    <section aria-label="Identity" className="overflow-hidden rounded-3xl border border-white bg-white shadow-[0_12px_30px_rgba(58,39,120,0.08)]">
      <div className="h-20 bg-gradient-to-br from-deep-violet via-[#7542a8] to-coral" />
      <div className="px-5 pb-5">
        <div className="flex min-w-0 items-center gap-3 pt-4">
          <div
            aria-hidden
            className="flex h-[70px] w-[70px] shrink-0 items-center justify-center rounded-2xl border-4 border-white bg-deep-violet text-xl font-black text-white shadow-lg"
          >
            {initialsOf(profile)}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="min-w-0 truncate text-[18px] font-black text-ink">{fullName(profile)}</h2>
              <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold ${profile.email_verified ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200" : "bg-amber-50 text-amber-700 ring-1 ring-amber-200"}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${profile.email_verified ? "bg-emerald-500" : "bg-amber-500"}`} />
                {profile.email_verified ? "Verified" : "Unverified"}
              </span>
            </div>
            <p className="mt-0.5 max-w-full truncate text-[12px] text-ink/55">{profile.email}</p>
          </div>
          <button
            onClick={onEdit}
            className="rounded-xl border border-ink/10 px-3.5 py-2 text-[11px] font-bold text-ink/65 transition hover:border-deep-violet/40 hover:text-deep-violet focus:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40"
          >
            Edit profile
          </button>
        </div>

        <div className="mt-5 grid grid-cols-3 divide-x divide-ink/[0.07] rounded-2xl bg-ink/[0.025] py-3">
          <div className="px-3 text-center first:pl-2 last:pr-2">
            <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-ink/40">Plan</p>
            <p className="mt-1 text-[12px] font-black capitalize text-deep-violet">{profile.plan}</p>
          </div>
          <div className="px-3 text-center first:pl-2 last:pr-2">
            <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-ink/40">Member since</p>
            <p className="mt-1 text-[12px] font-bold text-ink/70">{memberYear}</p>
          </div>
          <div className="px-3 text-center first:pl-2 last:pr-2">
            <p className="text-[9px] font-bold uppercase tracking-[0.12em] text-ink/40">Setup</p>
            <p className="mt-1 text-[12px] font-bold text-ink/70">{profile.onboarded ? "Complete" : "In progress"}</p>
          </div>
        </div>
      </div>
    </section>
  );
}
