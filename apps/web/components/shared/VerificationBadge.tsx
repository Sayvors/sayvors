import type { ReactNode } from "react";

/**
 * Reusable verified / unverified tag for any location or identity surface.
 *
 * `status` is the backend's verification state (see channels/router.py's
 * _verification_status): verified | pending | under_review | guidelines |
 * ownership_conflict | failed | required | unstarted. Only "verified" gets
 * the positive treatment; every other state is unverified with its own
 * short label, so a pending review is never shown as a clean green tag.
 */
export type VerificationStatus =
  | "verified"
  | "pending"
  | "under_review"
  | "guidelines"
  | "ownership_conflict"
  | "failed"
  | "required"
  | "unstarted";

const LABELS: Record<VerificationStatus, string> = {
  verified: "Verified",
  pending: "Pending",
  under_review: "Under review",
  guidelines: "Action needed",
  ownership_conflict: "Ownership conflict",
  failed: "Failed",
  required: "Verification needed",
  unstarted: "Unverified",
};

export function isVerified(status: string | null | undefined): boolean {
  return status === "verified";
}

export default function VerificationBadge({
  status,
  label,
  compact = false,
}: {
  status: string | null | undefined;
  /** Override the derived label, e.g. "Unverified" for a missing place id. */
  label?: string;
  compact?: boolean;
}): ReactNode {
  const key: VerificationStatus = isVerified(status)
    ? "verified"
    : (status as VerificationStatus) in LABELS
    ? (status as VerificationStatus)
    : "unstarted";
  const verified = key === "verified";
  const text = label ?? LABELS[key];

  return (
    <span
      role="status"
      title={verified ? "Google has verified this location" : `Verification: ${text}`}
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
        verified
          ? "border-[#0E5C36]/25 bg-[#DCF5E6] text-[#0E5C36]"
          : "border-[#B0338A]/25 bg-[#F4F2F7] text-[#3B2D5E]"
      }`}
    >
      <span
        aria-hidden
        className={`h-1.5 w-1.5 rounded-full ${verified ? "bg-[#0E5C36]" : "bg-[#B0338A]"}`}
      />
      {compact && !verified ? "Unverified" : text}
    </span>
  );
}
