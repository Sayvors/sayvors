"use client";

import { createAvatar } from "@bible-strong/avatar-react";
import definition from "@/lib/sayvors-guide.avatar.json";

const GuideAvatar = createAvatar(definition);

/** Mirrors the animation keys in lib/sayvors-guide.avatar.json. */
type GuideAnimation = "idle" | "invite" | "verify" | "almost" | "celebrate";

export default function SignupGuide({
  step,
  isLogin,
  busy,
}: {
  step: number;
  isLogin: boolean;
  busy?: boolean;
}) {
  // One expression per signup step, so the guide reacts to where the form actually is.
  // Submitting is the beat worth marking: the request is in flight long enough to see it
  // before the redirect to /verify-otp, and a validation failure leaves us here.
  const animation: GuideAnimation = isLogin
    ? "idle"
    : busy
      ? "celebrate"
      : step === 0
        ? "invite"
        : step === 1
          ? "verify"
          : "almost";

  return <GuideAvatar animation={animation} size={92} ariaLabel="Sayvors signup guide" />;
}