import type { Profile } from "./api-profile";

/**
 * The details that make a workspace recognisable. Kept in one place because
 * the hero badge and the strength card must never disagree.
 */
export interface CompletionCheck {
  label: string;
  done: boolean;
  hint: string;
}

export function profileChecks(profile: Profile): CompletionCheck[] {
  return [
    { label: "Name", done: Boolean(profile.first_name && profile.last_name), hint: "Add your full name" },
    { label: "Photo", done: Boolean(profile.avatar_url), hint: "Add a profile photo" },
    { label: "Phone", done: Boolean(profile.phone), hint: "Add a phone number" },
    { label: "Country", done: Boolean(profile.country), hint: "Set your country" },
    { label: "Business", done: Boolean(profile.business_name), hint: "Add your business name" },
    { label: "Bio", done: Boolean(profile.bio), hint: "Write a short bio" },
  ];
}

export function profileCompletion(profile: Profile): number {
  const checks = profileChecks(profile);
  const done = checks.filter((check) => check.done).length;
  return Math.round((done / checks.length) * 100);
}
