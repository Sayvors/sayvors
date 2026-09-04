"use client";

import Image from "next/image";

export default function ProfileHeader() {
  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 overflow-hidden">
      {/* Cover gradient */}
      <div className="h-28 bg-gradient-to-r from-deep-violet via-magenta to-coral" />

      <div className="px-5 pb-5">
        {/* Avatar */}
        <div className="-mt-12 flex items-end gap-4">
          <div className="relative h-20 w-20 shrink-0 rounded-2xl border-4 border-white bg-ink/[0.06] overflow-hidden shadow-lg">
            <Image
              src="/Sayvors_Icon.png"
              alt="Profile"
              fill
              className="object-cover"
            />
          </div>
          <div className="flex-1 pb-1">
            <h1 className="text-[18px] font-bold text-ink">Syed</h1>
            <p className="text-[12px] text-ink/45">syed@sayvors.com</p>
          </div>
          <button className="rounded-lg border-2 border-ink/10 px-3 py-1.5 text-[11px] font-semibold text-ink/50 transition hover:border-deep-violet/30 hover:text-deep-violet">
            Edit Profile
          </button>
        </div>

        {/* Plan badge */}
        <div className="mt-4 flex items-center gap-2">
          <span className="rounded-full bg-gradient-to-r from-deep-violet to-magenta px-3 py-1 text-[10px] font-bold text-white shadow-sm">
            Pro Plan
          </span>
          <span className="text-[11px] text-ink/40">Active since Jan 2026</span>
        </div>
      </div>
    </div>
  );
}
