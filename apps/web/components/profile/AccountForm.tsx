"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { BUSINESS_TYPES } from "@/lib/business-types";
import { COUNTRIES } from "@/lib/countries";
import type { Profile } from "@/lib/api-profile";

/** The subset of the profile this form owns. */
export interface AccountFormPatch {
  first_name: string;
  last_name: string;
  phone: string;
  country: string | null;
  business_name: string;
  business_type: string | null;
  bio: string;
}

const BIO_MAX = 2000;
const BUSINESS_NAME_MAX = 255;
const PHONE_PATTERN = /^[+()\-\s\d]{7,25}$/;

const CARD =
  "rounded-[32px] bg-white p-5 shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)] ring-1 ring-ink/[0.06] dark:bg-[#1b1530] dark:ring-white/[0.08] sm:p-7";

const INPUT =
  "w-full rounded-[20px] border bg-white px-4 py-3 text-[13.5px] text-ink outline-none transition placeholder:text-ink/30 focus:border-deep-violet/50 focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/25 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white/[0.04] dark:text-fog dark:placeholder:text-fog/30";

function valuesFrom(profile: Profile): AccountFormPatch {
  return {
    first_name: profile.first_name ?? "",
    last_name: profile.last_name ?? "",
    phone: profile.phone ?? "",
    country: profile.country ?? "",
    business_name: profile.business_name ?? "",
    business_type: profile.business_type ?? "",
    bio: profile.bio ?? "",
  };
}

function trimmed(values: AccountFormPatch): AccountFormPatch {
  return {
    first_name: values.first_name.trim(),
    last_name: values.last_name.trim(),
    phone: values.phone.trim(),
    country: values.country || null,
    business_name: values.business_name.trim(),
    // "Not set" is null, never an empty string — the API stores the category
    // verbatim and "" would defeat the "is it set?" checks everywhere.
    business_type: values.business_type?.trim() || null,
    bio: values.bio.trim(),
  };
}

function sameValues(a: AccountFormPatch, b: AccountFormPatch): boolean {
  return (
    a.first_name === b.first_name &&
    a.last_name === b.last_name &&
    a.phone === b.phone &&
    (a.country ?? "") === (b.country ?? "") &&
    a.business_name === b.business_name &&
    a.business_type === b.business_type &&
    a.bio === b.bio
  );
}

function validate(values: AccountFormPatch): Record<string, string> {
  const errors: Record<string, string> = {};
  if (values.first_name.length < 2) {
    errors.first_name = "Use at least 2 characters.";
  }
  if (values.last_name.length < 2) {
    errors.last_name = "Use at least 2 characters.";
  }
  if (values.phone && !PHONE_PATTERN.test(values.phone)) {
    errors.phone = "Use digits with an optional + and spaces, 7–25 characters.";
  }
  if (values.phone && values.phone.replace(/\D/g, "").length < 7) {
    errors.phone = "Enter at least 7 digits.";
  }
  if (values.business_name.length > BUSINESS_NAME_MAX) {
    errors.business_name = `Keep it under ${BUSINESS_NAME_MAX} characters.`;
  }
  if (values.bio.length > BIO_MAX) {
    errors.bio = `Keep it under ${BIO_MAX} characters.`;
  }
  return errors;
}

function fieldClasses(hasError: boolean): string {
  return `${INPUT} ${
    hasError
      ? "border-coral focus:border-coral focus-visible:outline-coral/30"
      : "border-ink/[0.12] dark:border-white/[0.12]"
  }`;
}

function Field({
  id,
  label,
  hint,
  error,
  className = "",
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={className}>
      <label htmlFor={id} className="block text-[12px] font-bold text-ink dark:text-fog">
        {label}
      </label>
      {hint && (
        <p id={`${id}-hint`} className="mt-0.5 text-[10.5px] text-ink/45 dark:text-fog/45">
          {hint}
        </p>
      )}
      <div className="mt-1.5">{children}</div>
      {error && (
        <p id={`${id}-error`} className="mt-1.5 text-[11px] font-semibold text-coral">
          {error}
        </p>
      )}
    </div>
  );
}

export default function AccountForm({
  profile,
  onSave,
}: {
  profile: Profile;
  onSave: (patch: AccountFormPatch) => Promise<Profile>;
}) {
  const [values, setValues] = useState<AccountFormPatch>(() => valuesFrom(profile));
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [attempted, setAttempted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const savedValues = valuesFrom(profile);
  const nextValues = trimmed(values);
  const dirty = !sameValues(nextValues, trimmed(savedValues));
  const errors = validate(nextValues);

  function update<K extends keyof AccountFormPatch>(key: K, value: AccountFormPatch[K]) {
    setValues((previous) => ({ ...previous, [key]: value }));
    setSaved(false);
    setServerError(null);
  }

  function touch(field: string) {
    setTouched((previous) => ({ ...previous, [field]: true }));
  }

  function showError(field: string): string | undefined {
    return touched[field] || attempted ? errors[field] : undefined;
  }

  function discard() {
    setValues(valuesFrom(profile));
    setTouched({});
    setAttempted(false);
    setServerError(null);
    setSaved(false);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAttempted(true);
    setServerError(null);
    if (!dirty || Object.keys(errors).length > 0) return;

    setSubmitting(true);
    try {
      const updated = await onSave(nextValues);
      setValues(valuesFrom(updated));
      setTouched({});
      setAttempted(false);
      setSaved(true);
    } catch (error) {
      setServerError(
        error instanceof Error && error.message
          ? error.message
          : "Could not save your details. Try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  // A stored category that predates the current list stays selectable instead
  // of silently resetting the field to the first option.
  const typeOptions: string[] = [...BUSINESS_TYPES];
  if (values.business_type && !typeOptions.includes(values.business_type)) {
    typeOptions.push(values.business_type);
  }

  return (
    <form onSubmit={handleSubmit} noValidate className={CARD} aria-labelledby="account-form-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="account-form-title" className="text-[17px] font-black tracking-tight text-ink dark:text-fog">
            Account details
          </h2>
          <p className="mt-0.5 text-[11.5px] text-ink/50 dark:text-fog/50">
            How your workspace identifies you to your team.
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold ${
            dirty
              ? "bg-amber-50 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-400/20"
              : "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-400/10 dark:text-emerald-300 dark:ring-emerald-400/20"
          }`}
        >
          <span
            aria-hidden
            className={`h-1.5 w-1.5 rounded-full ${dirty ? "bg-amber-500" : "bg-emerald-500"}`}
          />
          {dirty ? "Unsaved changes" : saved ? "Saved" : "Up to date"}
        </span>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Field id="account-first-name" label="First name" error={showError("first_name")}>
          <input
            id="account-first-name"
            name="given-name"
            autoComplete="given-name"
            value={values.first_name}
            onChange={(e) => update("first_name", e.target.value)}
            onBlur={() => touch("first_name")}
            aria-invalid={Boolean(showError("first_name"))}
            aria-describedby={showError("first_name") ? "account-first-name-error" : undefined}
            className={fieldClasses(Boolean(showError("first_name")))}
            placeholder="Sara"
            maxLength={100}
          />
        </Field>

        <Field id="account-last-name" label="Last name" error={showError("last_name")}>
          <input
            id="account-last-name"
            name="family-name"
            autoComplete="family-name"
            value={values.last_name}
            onChange={(e) => update("last_name", e.target.value)}
            onBlur={() => touch("last_name")}
            aria-invalid={Boolean(showError("last_name"))}
            aria-describedby={showError("last_name") ? "account-last-name-error" : undefined}
            className={fieldClasses(Boolean(showError("last_name")))}
            placeholder="Ahmad"
            maxLength={100}
          />
        </Field>

        <Field
          id="account-email"
          label="Sign-in email"
          hint="Used to sign in and receive receipts. Contact support to change it."
          className="sm:col-span-2"
        >
          <input
            id="account-email"
            type="email"
            value={profile.email}
            readOnly
            aria-describedby="account-email-hint"
            className={`${fieldClasses(false)} bg-ink/[0.03] dark:bg-white/[0.02]`}
          />
        </Field>

        <Field
          id="account-phone"
          label="Phone"
          hint="Optional. Used for account recovery only."
          error={showError("phone")}
        >
          <input
            id="account-phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            value={values.phone}
            onChange={(e) => update("phone", e.target.value)}
            onBlur={() => touch("phone")}
            aria-invalid={Boolean(showError("phone"))}
            aria-describedby={
              showError("phone") ? "account-phone-error account-phone-hint" : "account-phone-hint"
            }
            className={fieldClasses(Boolean(showError("phone")))}
            placeholder="+966 50 000 0000"
            maxLength={50}
          />
        </Field>

        <Field id="account-country" label="Country" hint="Sets the default region for your workspace.">
          <select
            id="account-country"
            autoComplete="country"
            value={values.country ?? ""}
            onChange={(e) => update("country", e.target.value)}
            className={fieldClasses(false)}
          >
            <option value="">Not set</option>
            {COUNTRIES.map((country) => (
              <option key={country.code} value={country.code}>
                {country.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <div className="my-6 h-px bg-ink/[0.07] dark:bg-white/[0.08]" />

      <div>
        <h3 className="text-[14px] font-black text-ink dark:text-fog">Business profile</h3>
        <p className="mt-0.5 text-[11.5px] text-ink/50 dark:text-fog/50">
          Grounds the AI in what you actually sell. Used across posts and replies.
        </p>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field
          id="account-business-name"
          label="Business name"
          error={showError("business_name")}
        >
          <input
            id="account-business-name"
            autoComplete="organization"
            value={values.business_name}
            onChange={(e) => update("business_name", e.target.value)}
            onBlur={() => touch("business_name")}
            aria-invalid={Boolean(showError("business_name"))}
            aria-describedby={
              showError("business_name") ? "account-business-name-error" : undefined
            }
            className={fieldClasses(Boolean(showError("business_name")))}
            placeholder="Sayvors Coffee"
            maxLength={BUSINESS_NAME_MAX}
          />
        </Field>

        <Field id="account-business-type" label="Business type">
          <select
            id="account-business-type"
            value={values.business_type ?? ""}
            onChange={(e) => update("business_type", e.target.value)}
            className={fieldClasses(false)}
          >
            <option value="">Not set</option>
            {typeOptions.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </select>
        </Field>

        <Field
          id="account-bio"
          label="Bio"
          hint={`${nextValues.bio.length}/${BIO_MAX} characters`}
          error={showError("bio")}
          className="sm:col-span-2"
        >
          <textarea
            id="account-bio"
            rows={4}
            value={values.bio}
            onChange={(e) => update("bio", e.target.value)}
            onBlur={() => touch("bio")}
            aria-invalid={Boolean(showError("bio"))}
            aria-describedby={showError("bio") ? "account-bio-error" : undefined}
            className={`${fieldClasses(Boolean(showError("bio")))} resize-y`}
            placeholder="A short line about you and the business."
            maxLength={BIO_MAX}
          />
        </Field>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-ink/[0.07] pt-5 dark:border-white/[0.08]">
        <p
          role="status"
          aria-live="polite"
          className={`text-[11.5px] font-semibold ${
            serverError ? "text-coral" : "text-ink/45 dark:text-fog/45"
          }`}
        >
          {serverError ??
            (dirty
              ? "Review your changes, then save."
              : saved
                ? "All changes saved."
                : "Everything is up to date.")}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={discard}
            disabled={!dirty || submitting}
            className="rounded-[20px] px-4 py-2.5 text-[12px] font-bold text-ink/55 transition hover:bg-ink/[0.05] focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet active:translate-y-0.5 active:scale-[0.98] disabled:opacity-40 dark:text-fog/55 dark:hover:bg-white/[0.06]"
          >
            Discard
          </button>
          <button
            type="submit"
            disabled={!dirty || submitting}
            className="inline-flex items-center gap-2 rounded-[20px] bg-deep-violet px-5 py-2.5 text-[12px] font-bold text-white shadow-[0_10px_20px_-12px_rgba(61,29,110,0.9)] transition hover:bg-deep-violet/90 focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet/40 active:translate-y-0.5 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting && (
              <span
                aria-hidden
                className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white"
              />
            )}
            {submitting ? "Saving…" : "Save changes"}
          </button>
        </div>
      </div>
    </form>
  );
}
