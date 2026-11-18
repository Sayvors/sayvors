"use client";

/* Business intake after onboarding.
 *
 * The cascade is not a one-time wizard — an owner who skipped it, changed
 * business, or opened a second location must be able to answer again. This
 * page reuses the exact onboarding component so the two paths cannot drift.
 */
import Link from "next/link";
import { useRouter } from "next/navigation";
import BusinessIntakeStep from "@/components/onboarding/BusinessIntakeStep";
import { useI18n } from "@/lib/i18n/I18nProvider";

export default function BusinessIntakeView({
  initialSection,
  initialQuestionKey,
}: {
  initialSection?: string;
  initialQuestionKey?: string;
}) {
  const router = useRouter();
  const { t } = useI18n();
  const c = t.dashboard.businessIntake;

  return (
    <div className="team-ui h-full overflow-y-auto bg-[#F5F5F5] p-4 sm:p-6">
      <div className="mx-auto max-w-lg">
        <Link
          href="/dashboard/databank"
          className="mb-4 inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--ui-ink-2)] hover:text-[var(--ui-ink)] focus-visible:outline focus-visible:outline-[3px] focus-visible:outline-deep-violet"
        >
          <span aria-hidden>←</span>
          {c.backToDatabank}
        </Link>
        <div className="rounded-[32px] border border-[var(--ui-line)] bg-white p-4 shadow-[0_18px_40px_-30px_rgba(20,16,31,0.5)] sm:p-6">
          <BusinessIntakeStep
            skipLabel={c.cancel}
            initialSection={initialSection}
            initialQuestionKey={initialQuestionKey}
            onComplete={() => router.push("/dashboard/databank")}
          />
        </div>
      </div>
    </div>
  );
}
