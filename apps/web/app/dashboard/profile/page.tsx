"use client";

import ProfileHeader from "@/components/profile/ProfileHeader";
import ProfileAbout from "@/components/profile/ProfileAbout";
import ProfileLimits from "@/components/profile/ProfileLimits";
import ProfileAccount from "@/components/profile/ProfileAccount";
import ProfilePreferences from "@/components/profile/ProfilePreferences";
import ProfileSupport from "@/components/profile/ProfileSupport";
import ProfileRatings from "@/components/profile/ProfileRatings";

export default function ProfilePage() {
  return (
    <div className="h-full overflow-y-auto bg-[#f3f0ff]">
      <div className="p-4 sm:p-6 space-y-5">
        <div>
          <h1 className="text-[20px] sm:text-[22px] font-bold text-ink">Profile</h1>
          <p className="mt-0.5 text-[12px] sm:text-[13px] text-ink/65">
            Manage your account, preferences, and subscription.
          </p>
        </div>

        <ProfileHeader />

        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-5">
            <ProfileAbout />
            <ProfileAccount />
            <ProfileRatings />
          </div>
          <div className="space-y-5">
            <ProfileLimits />
            <ProfilePreferences />
            <ProfileSupport />
          </div>
        </div>
      </div>
    </div>
  );
}
