"use client";

import { useState } from "react";
import LogoLoader from "@/components/LogoLoader";
import type { Profile } from "@/lib/api-profile";

export default function ProfileAccount({
  profile,
  saving,
  onSave,
}: {
  profile: Profile;
  saving: boolean;
  onSave: (data: { first_name: string; last_name: string; phone: string }) => Promise<void>;
}) {
  const [firstName, setFirstName] = useState(profile.first_name);
  const [lastName, setLastName] = useState(profile.last_name);
  const [phone, setPhone] = useState(profile.phone ?? "");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty =
    firstName.trim() !== profile.first_name ||
    lastName.trim() !== profile.last_name ||
    phone.trim() !== (profile.phone ?? "");

  const nameValid = firstName.trim().length >= 2 && lastName.trim().length >= 2;

  async function handleSave() {
    if (!nameValid) {
      setError("First and last name need at least 2 characters.");
      return;
    }
    setError(null);
    try {
      await onSave({ first_name: firstName.trim(), last_name: lastName.trim(), phone: phone.trim() });
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save. Try again.");
    }
  }

  function handleCancel() {
    setFirstName(profile.first_name);
    setLastName(profile.last_name);
    setPhone(profile.phone ?? "");
    setEditing(false);
    setError(null);
  }

  return (
    <section aria-label="Account" className="rounded-2xl border border-ink/10 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-[14px] font-bold text-ink">Account</h3>
          <p className="text-[11px] text-ink/45">Identity used across Sayvors.</p>
        </div>
        {!editing ? (
          <button
            onClick={() => setEditing(true)}
            className="rounded text-[12px] font-semibold text-deep-violet hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-deep-violet/40"
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
              disabled={saving || !dirty || !nameValid}
              className="rounded-lg bg-deep-violet px-3 py-1.5 text-[12px] font-bold text-white transition hover:bg-deep-violet/90 disabled:opacity-50"
            >
              {saving ? (
                <span className="inline-flex items-center gap-1.5"><LogoLoader size={14} /> Saving…</span>
              ) : "Save"}
            </button>
          </div>
        )}
      </div>

      <dl className="space-y-4">
        <div>
          <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink/45">Email</dt>
          <dd className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-ink/80">
            <span className="break-all">{profile.email}</span>
            {profile.email_verified ? (
              <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-200">
                Verified
              </span>
            ) : (
              <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700 ring-1 ring-amber-200">
                Verify in your inbox
              </span>
            )}
          </dd>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="profile-first" className="text-[10px] font-semibold uppercase tracking-wider text-ink/45">
              First name
            </label>
            {editing ? (
              <input
                id="profile-first"
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                maxLength={100}
                className="mt-1 w-full rounded-lg border border-ink/15 bg-fog/40 px-3 py-2 text-[13px] focus:border-deep-violet/50 focus:outline-none focus:ring-2 focus:ring-deep-violet/20"
              />
            ) : (
              <p className="mt-1 text-[13px] text-ink/80">{profile.first_name}</p>
            )}
          </div>
          <div>
            <label htmlFor="profile-last" className="text-[10px] font-semibold uppercase tracking-wider text-ink/45">
              Last name
            </label>
            {editing ? (
              <input
                id="profile-last"
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                maxLength={100}
                className="mt-1 w-full rounded-lg border border-ink/15 bg-fog/40 px-3 py-2 text-[13px] focus:border-deep-violet/50 focus:outline-none focus:ring-2 focus:ring-deep-violet/20"
              />
            ) : (
              <p className="mt-1 text-[13px] text-ink/80">{profile.last_name}</p>
            )}
          </div>
        </div>

        <div>
          <label htmlFor="profile-phone" className="text-[10px] font-semibold uppercase tracking-wider text-ink/45">
            Phone
          </label>
          {editing ? (
            <input
              id="profile-phone"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              maxLength={50}
              placeholder="+1 (555) 000-0000"
              className="mt-1 w-full rounded-lg border border-ink/15 bg-fog/40 px-3 py-2 text-[13px] focus:border-deep-violet/50 focus:outline-none focus:ring-2 focus:ring-deep-violet/20"
            />
          ) : (
            <p className="mt-1 text-[13px] text-ink/80">
              {profile.phone?.trim() ? profile.phone : <span className="text-ink/35">No phone added.</span>}
            </p>
          )}
        </div>
      </dl>

      {error && <p role="alert" className="mt-3 text-[12px] font-medium text-coral">{error}</p>}
    </section>
  );
}
