"use client";

import { useState } from "react";

export default function ProfileAbout() {
  const [bio, setBio] = useState("Building the future of AI-powered customer service. Passionate about automation and smart workflows.");
  const [business, setBusiness] = useState("Sayvors - AI Customer Service Platform");
  const [editing, setEditing] = useState(false);

  return (
    <div className="rounded-2xl border-2 border-white bg-white/80 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-[14px] font-bold text-ink">About</h2>
        <button
          onClick={() => setEditing(!editing)}
          className="text-[11px] font-semibold text-deep-violet transition hover:text-deep-violet/80"
        >
          {editing ? "Save" : "Edit"}
        </button>
      </div>

      <div className="space-y-4">
        <div>
          <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Bio</label>
          {editing ? (
            <textarea
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              rows={3}
              className="mt-1 w-full rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink transition focus:border-deep-violet/30 focus:outline-none resize-none"
            />
          ) : (
            <p className="mt-1 text-[12px] text-ink/70">{bio}</p>
          )}
        </div>

        <div>
          <label className="text-[10px] font-semibold text-ink/40 uppercase tracking-wider">Business</label>
          {editing ? (
            <input
              type="text"
              value={business}
              onChange={(e) => setBusiness(e.target.value)}
              className="mt-1 w-full rounded-lg border-2 border-ink/[0.06] bg-ink/[0.02] px-3 py-2 text-[12px] text-ink transition focus:border-deep-violet/30 focus:outline-none"
            />
          ) : (
            <p className="mt-1 text-[12px] text-ink/70">{business}</p>
          )}
        </div>
      </div>
    </div>
  );
}
