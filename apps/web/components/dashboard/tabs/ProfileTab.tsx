"use client";

import { ChannelLogo } from "../ChannelLogos";

interface ProfileTabProps {
  channelSlug: string;
  channelName: string;
}

const profileData: Record<string, { username: string; followers: string; following: string; posts: string; bio: string; verified: boolean }> = {
  instagram: { username: "@sayvors", followers: "12.4K", following: "845", posts: "234", bio: "Building the future of AI-powered customer engagement. DM us for support!", verified: true },
  whatsapp: { username: "Sayvors Business", followers: "N/A", following: "N/A", posts: "N/A", bio: "Official WhatsApp Business account for Sayvors support and sales.", verified: true },
  facebook: { username: "Sayvors", followers: "8.2K", following: "120", posts: "567", bio: "AI-powered messaging platform for modern businesses.", verified: true },
  telegram: { username: "@sayvors_bot", followers: "5.6K", following: "N/A", posts: "89", bio: "Your intelligent assistant on Telegram. Type /help to get started.", verified: false },
  x: { username: "@sayvors", followers: "15.8K", following: "312", posts: "1,204", bio: "AI agents that actually work. Multi-channel messaging, automated support, and lead generation.", verified: true },
  linkedin: { username: "Sayvors Inc.", followers: "3.2K", following: "456", posts: "178", bio: "Enterprise AI messaging platform. Trusted by 500+ businesses worldwide.", verified: true },
};

export default function ProfileTab({ channelSlug, channelName }: ProfileTabProps) {
  const profile = profileData[channelSlug] || profileData.instagram;

  return (
    <div className="p-4 sm:p-6 space-y-6">
      <div>
        <h2 className="text-[16px] font-bold text-ink">{channelName} Profile</h2>
        <p className="mt-0.5 text-[13px] text-ink/60">Your public profile information.</p>
      </div>

      {/* Profile Card */}
      <div className="rounded-2xl border-2 border-white bg-white/80 p-5 sm:p-6">
        <div className="flex flex-col sm:flex-row items-start gap-4">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-deep-violet to-magenta text-[28px] text-white shadow-lg shadow-deep-violet/20 overflow-hidden">
            <ChannelLogo channel={channelSlug} className="h-10 w-10" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h3 className="text-[18px] font-bold text-ink">{profile.username}</h3>
              {profile.verified && (
                <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5 text-deep-violet">
                  <circle cx="12" cy="12" r="10" fill="currentColor" />
                  <path d="M8 12l3 3 5-5" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </div>
            <p className="mt-1 text-[13px] text-ink/60 leading-relaxed">{profile.bio}</p>
          </div>
        </div>

        {/* Stats */}
        <div className="mt-6 grid grid-cols-3 gap-4 border-t border-deep-violet/[0.06] pt-5">
          <div className="text-center">
            <p className="text-[20px] font-bold text-ink">{profile.followers}</p>
            <p className="text-[11px] font-semibold text-ink/45">Followers</p>
          </div>
          <div className="text-center">
            <p className="text-[20px] font-bold text-ink">{profile.following}</p>
            <p className="text-[11px] font-semibold text-ink/45">Following</p>
          </div>
          <div className="text-center">
            <p className="text-[20px] font-bold text-ink">{profile.posts}</p>
            <p className="text-[11px] font-semibold text-ink/45">Posts</p>
          </div>
        </div>
      </div>

      {/* Edit Profile */}
      <div className="rounded-2xl border-2 border-white bg-white/80 p-5 sm:p-6">
        <h3 className="mb-4 text-[14px] font-bold text-ink">Edit Profile</h3>
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-[12px] font-semibold text-ink/60">Display Name</label>
            <input
              type="text"
              defaultValue={profile.username}
              className="w-full rounded-xl border-2 border-white bg-white px-4 py-2.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
            />
          </div>
          <div>
            <label className="mb-1.5 block text-[12px] font-semibold text-ink/60">Bio</label>
            <textarea
              defaultValue={profile.bio}
              rows={3}
              className="w-full rounded-xl border-2 border-white bg-white px-4 py-2.5 text-[13px] text-ink outline-none focus:border-deep-violet/40 focus:ring-2 focus:ring-deep-violet/10"
            />
          </div>
          <button className="rounded-xl bg-deep-violet px-5 py-2.5 text-[12px] font-bold text-white shadow-md shadow-deep-violet/25 transition hover:bg-deep-violet/90 active:scale-[0.98]">
            Save Profile
          </button>
        </div>
      </div>
    </div>
  );
}
