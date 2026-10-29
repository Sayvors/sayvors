"use client";

import type { Profile } from "@/lib/api-profile";
import { profileChecks } from "@/lib/profile-completion";

const CARD =
  "rounded-[32px] bg-white p-5 shadow-[0_18px_44px_-30px_rgba(61,29,110,0.45)] ring-1 ring-ink/[0.06] dark:bg-[#1b1530] dark:ring-white/[0.08] sm:p-7";

export default function ProfileStrength({ profile }: { profile: Profile }) {
  const checks = profileChecks(profile);
  const done = checks.filter((check) => check.done).length;
  const percent = Math.round((done / checks.length) * 100);
  const missing = checks.filter((check) => !check.done);

  const tone =
    percent >= 80
      ? { bar: "bg-emerald-500", text: "text-emerald-700 dark:text-emerald-300" }
      : percent >= 50
        ? { bar: "bg-amber-500", text: "text-amber-700 dark:text-amber-300" }
        : { bar: "bg-coral", text: "text-coral" };

  return (
    <section aria-labelledby="strength-title" className={CARD}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 id="strength-title" className="text-[17px] font-black tracking-tight text-ink dark:text-fog">
            Profile strength
          </h2>
          <p className="mt-0.5 text-[11.5px] text-ink/50 dark:text-fog/50">
            {done} of {checks.length} details complete.
          </p>
        </div>
        <span className={`text-[24px] font-black tabular-nums leading-none ${tone.text}`}>
          {percent}%
        </span>
      </div>

      <div
        className="mt-4 h-2.5 w-full overflow-hidden rounded-full bg-ink/[0.07] dark:bg-white/[0.09]"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={`${percent}% complete`}
        aria-label="Profile strength"
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${tone.bar}`}
          style={{ width: `${percent}%` }}
        />
      </div>

      {missing.length === 0 ? (
        <p className="mt-4 text-[11.5px] font-semibold text-emerald-700 dark:text-emerald-300">
          Your profile is complete.
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {missing.slice(0, 4).map((check) => (
            <li key={check.label} className="flex items-center gap-2 text-[11.5px] text-ink/55 dark:text-fog/55">
              <span
                aria-hidden
                className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-ink/20 text-[9px] font-bold text-ink/40 dark:border-white/25 dark:text-fog/40"
              >
                +
              </span>
              {check.hint}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
