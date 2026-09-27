/**
 * The closed subject vocabulary.
 *
 * These are the only values a review's meaning may take. The list mirrors the
 * server's `analytics/subjects.py` exactly — a mismatch would let a correction
 * be rejected by the API for a value the UI offered, so the keys are asserted
 * against the server list in the test suite rather than trusted by eye.
 *
 * The point of a closed list is that a category nobody defined cannot be
 * invented. "Account Issues" is not a subject, so it cannot be produced, no
 * matter what the model feels like returning.
 */
export const MEANING_SUBJECTS: { value: string; label: string }[] = [
  { value: "product_quality", label: "Product quality" },
  { value: "features_updates", label: "Features & updates" },
  { value: "staff_service", label: "Staff & service" },
  { value: "cleanliness", label: "Cleanliness" },
  { value: "speed_waiting", label: "Speed & waiting" },
  { value: "value_pricing", label: "Value & pricing" },
  { value: "communication_response", label: "Communication & response" },
  { value: "facility_premises", label: "Facility & premises" },
  { value: "location_access", label: "Location & access" },
  { value: "delivery", label: "Delivery" },
  { value: "billing_payments", label: "Billing & payments" },
  { value: "account_access", label: "Account & access" },
  { value: "other", label: "Other" },
];

export const SUBJECT_LABELS: Record<string, string> = Object.fromEntries(
  MEANING_SUBJECTS.map((s) => [s.value, s.label])
);

export function subjectLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return SUBJECT_LABELS[value] ?? value;
}

/** Subjects where praise is the expected reading, not a complaint. */
export const PRAISE_SUBJECTS = new Set([
  "product_quality",
  "features_updates",
  "staff_service",
  "cleanliness",
  "value_pricing",
]);
