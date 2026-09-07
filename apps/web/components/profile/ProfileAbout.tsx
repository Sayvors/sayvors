"use client";

import { useState } from "react";
import LogoLoader from "@/components/LogoLoader";

export default function ProfileAbout({
  bio,
  businessName,
  saving,
  onSave,
}: {
  bio: string | null;
  businessName: string | null;
  saving: boolean;
  onSave: (data: { bio: string; business_name: string }) => Promise<void>;
}) {
  const [draftBio, setDraftBio] = useState(bio ?? "");
  const [draftBusiness, setDraftBusiness] = useState(businessName ?? "");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty =
    draftBio !== (bio ?? "") || draftBusiness !== (businessName ?? "");

  async function handleSave() {
    setError(null);
    try {
      await onSave({ bio: draftBio.trim(), business_name: draftBusiness.trim() });
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save. Try again.");
    }
  }

  function handleCancel() {
    setDraftBio(bio ?? "");
    setDraftBusiness(businessName ?? "");
    setEditing(false);
    setError(null);
  }

  return (
    <section aria-label="About" className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-[14px] font-bold text-ink">About</h3>
          <p className="text-[11px] text-ink/45">Tell your team who you are.</p>
        </div>
        {!editing ? (
          <button
            onClick={() => setEditing(true)}
            className="text-[12px] font-semibold text-deep-violet hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40 rounded"
          >
            Edit
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={handleCancel}
              disabled={saving}
              className="rounded-lg px-3 py-1.5 text-[12px] font-semibold text-ink/60 hover:text-ink disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !dirty}
              className="rounded-lg bg-deep-violet px-3 py-1.5 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
            >
              {saving ? (
                <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving…</span>
              ) : "Save"}
            </button>
          </div>
        )}
      </div>

      <div className="space-y-4">
        <div>
          <label htmlFor="profile-bio" className="text-[10px] font-semibold uppercase tracking-wider text-ink/45">
            Bio
          </label>
          {editing ? (
            <textarea
              id="profile-bio"
              value={draftBio}
              onChange={(e) => setDraftBio(e.target.value)}
              rows={3}
              maxLength={2000}
              placeholder="What do you do? What is your business about?"
              className="mt-1 w-full resize-none rounded-lg border border-ink/15 bg-fog/40 px-3 py-2 text-[13px] text-ink transition focus:border-deep-violet/50 focus:outline-none focus:ring-2 focus:ring-deep-violet/20"
            />
          ) : (
            <p className="mt-1 text-[13px] leading-relaxed text-ink/75">
              {bio?.trim() ? bio : <span className="text-ink/35">No bio yet — add one so collaborators recognize you.</span>}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="profile-business" className="text-[10px] font-semibold uppercase tracking-wider text-ink/45">
            Business
          </label>
          {editing ? (
            <input
              id="profile-business"
              type="text"
              value={draftBusiness}
              onChange={(e) => setDraftBusiness(e.target.value)}
              maxLength={255}
              placeholder="Business or organization name"
              className="mt-1 w-full rounded-lg border border-ink/15 bg-fog/40 px-3 py-2 text-[13px] text-ink transition focus:border-deep-violet/50 focus:outline-none focus:ring-2 focus:ring-deep-violet/20"
            />
          ) : (
            <p className="mt-1 text-[13px] text-ink/75">
              {businessName?.trim() ? businessName : <span className="text-ink/35">No business set.</span>}
            </p>
          )}
        </div>

        {error && <p role="alert" className="text-[12px] font-medium text-coral">{error}</p>}
      </div>
    </section>
  );
}
