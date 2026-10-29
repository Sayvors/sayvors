"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  fullName,
  initialsOf,
  type AvatarSource,
  type Profile,
} from "@/lib/api-profile";
import { DeviceMark, FacebookMark, GoogleMark } from "./ProviderMarks";

export type ProfileImageKind = "avatar" | "cover";

const ACCEPTED = "image/png,image/jpeg,image/webp";
const MAX_AVATAR_BYTES = 8 * 1024 * 1024;
const MAX_COVER_BYTES = 12 * 1024 * 1024;

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

function CameraIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[18px] w-[18px]"
      aria-hidden
    >
      <path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.2a2 2 0 0 0 1.7-.95l.55-.9A1.5 1.5 0 0 1 11.2 3h1.6a1.5 1.5 0 0 1 1.25.65l.55.9A2 2 0 0 0 16.3 6h1.2A2.5 2.5 0 0 1 20 8.5v8A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5z" />
      <circle cx="12" cy="12.2" r="3.4" />
    </svg>
  );
}

function ImageIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4"
      aria-hidden
    >
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <circle cx="8.5" cy="9.5" r="1.5" />
      <path d="m4 17 4.6-4.2a2 2 0 0 1 2.7 0L16 17" />
      <path d="m14 14 1.7-1.5a2 2 0 0 1 2.6 0L21 15" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-3 w-3"
      aria-hidden
    >
      <path d="m3.5 8.5 3 3 6-7" />
    </svg>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden
      className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  );
}

export default function AccountHero({
  profile,
  completion,
  busy,
  onUpload,
  onSelectSource,
  onRemoveAvatar,
  onRemoveCover,
}: {
  profile: Profile;
  completion: number;
  busy: "avatar" | "cover" | "source" | null;
  onUpload: (kind: ProfileImageKind, file: File) => Promise<void>;
  onSelectSource: (source: AvatarSource) => Promise<void>;
  onRemoveAvatar: () => Promise<void>;
  onRemoveCover: () => Promise<void>;
}) {
  const avatarInput = useRef<HTMLInputElement>(null);
  const coverInput = useRef<HTMLInputElement>(null);
  const previewUrl = useRef<string | null>(null);

  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [coverPreview, setCoverPreview] = useState<string | null>(null);
  const [failedAvatar, setFailedAvatar] = useState<string | null>(null);
  const [failedCover, setFailedCover] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<"avatar" | "cover" | null>(null);

  const avatarSrc =
    avatarPreview ??
    (profile.avatar_url && failedAvatar !== profile.avatar_url
      ? profile.avatar_url
      : null);
  const coverSrc =
    coverPreview ??
    (profile.cover_url && failedCover !== profile.cover_url
      ? profile.cover_url
      : null);
  const memberYear = new Date(profile.member_since).getFullYear() || null;

  useEffect(() => {
    return () => {
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    };
  }, []);

  useEffect(() => {
    if (!confirmRemove) return;
    const timer = window.setTimeout(() => setConfirmRemove(null), 4000);
    return () => window.clearTimeout(timer);
  }, [confirmRemove]);

  function makePreview(file: File): string {
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    const url = URL.createObjectURL(file);
    previewUrl.current = url;
    return url;
  }

  function validate(file: File, kind: ProfileImageKind) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      throw new Error("Choose a JPG, PNG or WEBP image.");
    }
    const max = kind === "avatar" ? MAX_AVATAR_BYTES : MAX_COVER_BYTES;
    if (file.size > max) {
      throw new Error(`That image is too large — max ${Math.round(max / (1024 * 1024))} MB.`);
    }
  }

  async function handleFile(kind: ProfileImageKind, file: File | undefined) {
    if (!file) return;
    setError(null);
    try {
      validate(file, kind);
      const url = makePreview(file);
      if (kind === "avatar") setAvatarPreview(url);
      else setCoverPreview(url);
      await onUpload(kind, file);
    } catch (e) {
      setError(messageOf(e, "Could not upload that image."));
    } finally {
      if (kind === "avatar") setAvatarPreview(null);
      else setCoverPreview(null);
    }
  }

  async function choose(source: AvatarSource) {
    if (source === "upload") {
      // Existing device photo and not selected: switch to it. Otherwise open
      // the picker so the active chip always means "change this photo".
      if (profile.avatar_upload_url && profile.avatar_source !== "upload") {
        await run(() => onSelectSource("upload"), "Could not switch photo.");
      } else {
        avatarInput.current?.click();
      }
      return;
    }
    if (profile.avatar_source === source) return;
    await run(() => onSelectSource(source), "Could not switch photo.");
  }

  async function run(action: () => Promise<void>, fallback: string) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(messageOf(e, fallback));
    }
  }

  async function removeAvatar() {
    if (confirmRemove !== "avatar") {
      setConfirmRemove("avatar");
      return;
    }
    setConfirmRemove(null);
    await run(onRemoveAvatar, "Could not remove the photo.");
  }

  async function removeCover() {
    if (confirmRemove !== "cover") {
      setConfirmRemove("cover");
      return;
    }
    setConfirmRemove(null);
    await run(onRemoveCover, "Could not remove the cover.");
  }

  const sourceChips: {
    id: AvatarSource;
    label: string;
    icon: ReactNode;
    disabled: boolean;
    title: string;
  }[] = [
    {
      id: "google",
      label: "Google",
      icon: <GoogleMark />,
      disabled: !profile.google_avatar_url,
      title: profile.google_avatar_url
        ? "Use the photo from your Google account"
        : profile.google_connected
          ? "Google is connected but has not shared a photo yet"
          : "Sign in with Google to use its photo",
    },
    {
      id: "facebook",
      label: "Facebook",
      icon: <FacebookMark />,
      disabled: !profile.facebook_avatar_url,
      title: profile.facebook_avatar_url
        ? "Use the photo from your Facebook account"
        : profile.facebook_connected
          ? "Facebook is connected but has not shared a photo yet"
          : "Sign in with Facebook to use its photo",
    },
    {
      id: "upload",
      label: "Device",
      icon: <DeviceMark />,
      disabled: false,
      title: profile.avatar_upload_url
        ? "Use the photo uploaded from this device"
        : "Upload a photo from this device",
    },
  ];

  return (
    <section
      aria-label="Profile photos"
      className="overflow-hidden rounded-[32px] bg-white shadow-[0_24px_60px_-30px_rgba(61,29,110,0.35)] ring-1 ring-ink/[0.06] dark:bg-[#1b1530] dark:ring-white/[0.08]"
    >
      {/* Cover — a solid brand panel when empty, never a gradient. */}
      <div className="relative h-40 overflow-hidden bg-deep-violet sm:h-52">
        <span aria-hidden className="absolute -left-16 -top-24 h-64 w-64 rounded-full bg-white/[0.06]" />
        <span aria-hidden className="absolute -right-10 top-8 h-40 w-40 rounded-full bg-magenta/30" />
        <span aria-hidden className="absolute -bottom-24 left-1/3 h-56 w-56 rounded-full bg-coral/20" />
        <svg aria-hidden className="absolute inset-0 h-full w-full opacity-[0.07]">
          <defs>
            <pattern id="profile-cover-grid" width="34" height="34" patternUnits="userSpaceOnUse">
              <path d="M34 0H0V34" fill="none" stroke="white" strokeWidth="1" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#profile-cover-grid)" />
        </svg>

        {coverSrc && (
          // eslint-disable-next-line @next/next/no-img-element -- user media is a runtime URL, not a build-time asset
          <img
            src={coverSrc}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
            onError={() => setFailedCover(profile.cover_url)}
          />
        )}

        <div className="absolute right-3 top-3 flex items-center gap-2 sm:right-4 sm:top-4">
          <button
            type="button"
            onClick={() => coverInput.current?.click()}
            disabled={busy !== null}
            className="inline-flex items-center gap-1.5 rounded-full bg-white px-3 py-2 text-[11px] font-bold text-ink shadow-[0_6px_16px_rgba(20,16,31,0.18)] transition hover:bg-fog focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-white disabled:opacity-60 sm:px-3.5"
          >
            {busy === "cover" ? <Spinner /> : <ImageIcon />}
            <span className="hidden sm:inline">Change cover</span>
            <span className="sm:hidden">Cover</span>
          </button>
          {profile.cover_url && (
            <button
              type="button"
              onClick={removeCover}
              disabled={busy !== null}
              className={`rounded-full px-3 py-2 text-[11px] font-bold shadow-[0_6px_16px_rgba(20,16,31,0.18)] transition focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-white disabled:opacity-60 ${
                confirmRemove === "cover"
                  ? "bg-coral text-white"
                  : "bg-white text-ink/60 hover:text-coral"
              }`}
            >
              {confirmRemove === "cover" ? "Sure?" : "Remove"}
            </button>
          )}
        </div>
      </div>

      <div className="px-5 pb-6 sm:px-8 sm:pb-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:gap-6">
          <div className="-mt-14 shrink-0 sm:-mt-16">
            <div className="relative h-28 w-28 rounded-full bg-deep-violet p-1 shadow-[0_18px_36px_-16px_rgba(61,29,110,0.55)] sm:h-32 sm:w-32">
              <div className="relative flex h-full w-full items-center justify-center overflow-hidden rounded-full bg-deep-violet text-[30px] font-black tracking-wide text-white">
                {avatarSrc ? (
                  // eslint-disable-next-line @next/next/no-img-element -- provider/upload URL is runtime data
                  <img
                    src={avatarSrc}
                    alt={`${fullName(profile)} profile photo`}
                    className="h-full w-full object-cover"
                    onError={() => setFailedAvatar(profile.avatar_url)}
                  />
                ) : (
                  <span aria-hidden>{initialsOf(profile)}</span>
                )}
                {busy === "avatar" && (
                  <span className="absolute inset-0 flex items-center justify-center bg-ink/45 text-white">
                    <Spinner />
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => avatarInput.current?.click()}
                disabled={busy !== null}
                aria-label="Upload a profile photo from this device"
                title="Upload a profile photo"
                className="absolute bottom-0.5 right-0.5 flex h-10 w-10 items-center justify-center rounded-full bg-white text-deep-violet shadow-[0_6px_16px_rgba(20,16,31,0.2)] ring-1 ring-ink/[0.06] transition hover:bg-deep-violet hover:text-white focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet disabled:opacity-60"
              >
                <CameraIcon />
              </button>
            </div>
          </div>

          <div className="min-w-0 flex-1 sm:pb-1">
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
              <h2 className="truncate text-[24px] font-black tracking-tight text-ink dark:text-fog sm:text-[28px]">
                {fullName(profile)}
              </h2>
              <span
                className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold ${
                  profile.email_verified
                    ? "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200 dark:bg-emerald-400/10 dark:text-emerald-300 dark:ring-emerald-400/20"
                    : "bg-amber-50 text-amber-700 ring-1 ring-amber-200 dark:bg-amber-400/10 dark:text-amber-300 dark:ring-amber-400/20"
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    profile.email_verified ? "bg-emerald-500" : "bg-amber-500"
                  }`}
                  aria-hidden
                />
                {profile.email_verified ? "Verified" : "Unverified"}
              </span>
            </div>
            <p className="mt-1 truncate text-[13px] text-ink/55 dark:text-fog/55">{profile.email}</p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {memberYear && (
                <span className="inline-flex items-center rounded-full bg-ink/[0.045] px-2.5 py-1 text-[10.5px] font-semibold text-ink/60 dark:bg-white/[0.06] dark:text-fog/60">
                  Member since {memberYear}
                </span>
              )}
              <span className="inline-flex items-center rounded-full bg-ink/[0.045] px-2.5 py-1 text-[10.5px] font-semibold text-ink/60 dark:bg-white/[0.06] dark:text-fog/60">
                {completion}% complete
              </span>
            </div>
          </div>
        </div>

        <div className="mt-6 rounded-[24px] border border-ink/[0.055] bg-[#f7f4fd] p-4 dark:border-white/[0.07] dark:bg-white/[0.035] sm:mt-7 sm:p-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="min-w-0">
              <p className="text-[13px] font-bold text-ink dark:text-fog">Profile photo</p>
              <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink/50 dark:text-fog/50">
                Pick the picture Sayvors shows across your workspace.
              </p>
            </div>

            <div
              role="group"
              aria-label="Profile photo source"
              className="flex w-full shrink-0 flex-wrap gap-1 rounded-full bg-white p-1 shadow-[0_4px_14px_rgba(61,29,110,0.08)] ring-1 ring-ink/[0.06] dark:bg-white/[0.06] dark:ring-white/[0.08] lg:w-auto"
            >
              {sourceChips.map((chip) => {
                const active = profile.avatar_source === chip.id;
                return (
                  <button
                    key={chip.id}
                    type="button"
                    aria-pressed={active}
                    disabled={chip.disabled || busy !== null}
                    title={chip.title}
                    onClick={() => void choose(chip.id)}
                    className={`inline-flex flex-1 items-center justify-center gap-1.5 rounded-full px-3 py-2 text-[11.5px] font-bold transition focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet disabled:cursor-not-allowed disabled:opacity-40 lg:flex-none ${
                      active
                        ? "bg-deep-violet text-white shadow-[0_4px_12px_rgba(61,29,110,0.28)]"
                        : "text-ink/60 hover:bg-ink/[0.045] hover:text-ink dark:text-fog/60 dark:hover:bg-white/[0.06] dark:hover:text-fog"
                    }`}
                  >
                    {chip.icon}
                    <span>{chip.label}</span>
                    {active && <CheckIcon />}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[10.5px] text-ink/40 dark:text-fog/40">
              JPG, PNG or WEBP · up to 8 MB. Google and Facebook photos refresh when you sign in.
            </p>
            {profile.avatar_url && (
              <button
                type="button"
                onClick={removeAvatar}
                disabled={busy !== null}
                className={`text-[10.5px] font-bold transition focus:outline-none focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet disabled:opacity-50 ${
                  confirmRemove === "avatar"
                    ? "text-coral"
                    : "text-ink/45 hover:text-coral dark:text-fog/45"
                }`}
              >
                {confirmRemove === "avatar" ? "Click again to remove" : "Remove photo"}
              </button>
            )}
          </div>

          {profile.avatar_source === "none" && !error && (
            <p className="mt-2 text-[10.5px] font-semibold text-ink/45 dark:text-fog/45">
              No photo selected — your initials are shown instead.
            </p>
          )}
          {error && (
            <p role="alert" className="mt-2 text-[11.5px] font-semibold text-coral">
              {error}
            </p>
          )}
        </div>
      </div>

      <input
        ref={avatarInput}
        type="file"
        accept={ACCEPTED}
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          void handleFile("avatar", file);
        }}
      />
      <input
        ref={coverInput}
        type="file"
        accept={ACCEPTED}
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          void handleFile("cover", file);
        }}
      />
    </section>
  );
}
