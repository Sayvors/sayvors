"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import Breadcrumbs from "@/components/Breadcrumbs";
import PlatformMark from "@/components/channels/PlatformMark";

/**
 * Shared frame for the per-channel onboarding screens.
 *
 * Deliberately one column of content with a small "why / what you need"
 * rail: the tenant is here to finish a provider hand-off, so the wizard is
 * the only thing competing for attention.
 */

export interface OnboardingStep {
  key: string;
  label: string;
}

const PLATFORM_COPY: Record<
  string,
  { name: string; hub: string; accent: string; soft: string }
> = {
  whatsapp: {
    name: "WhatsApp",
    hub: "/dashboard/channels/whatsapp",
    accent: "text-emerald-700 dark:text-emerald-300",
    soft: "bg-emerald-600/10",
  },
  facebook: {
    name: "Facebook",
    hub: "/dashboard/channels/facebook",
    accent: "text-blue-700 dark:text-blue-300",
    soft: "bg-blue-600/10",
  },
  instagram: {
    name: "Instagram",
    hub: "/dashboard/channels/instagram",
    accent: "text-pink-700 dark:text-pink-300",
    soft: "bg-pink-600/10",
  },
};

export default function OnboardingShell({
  platform,
  title,
  subtitle,
  steps,
  current,
  onStepClick,
  children,
  aside,
}: {
  platform: "whatsapp" | "facebook" | "instagram";
  title: string;
  subtitle: string;
  steps: OnboardingStep[];
  current: number;
  /** Only completed steps are clickable — forward jumps stay gated. */
  onStepClick?: (index: number) => void;
  children: ReactNode;
  aside?: ReactNode;
}) {
  const copy = PLATFORM_COPY[platform];

  return (
    <div className="h-full overflow-y-auto p-4 pb-24 sm:p-6">
      <div className="mx-auto w-full max-w-5xl">
        <Breadcrumbs
          items={[
            { label: "Channels", href: "/dashboard/channels" },
            { label: copy.name, href: copy.hub },
            { label: "Connect" },
          ]}
        />

        <header className="mt-3 flex items-start gap-3">
          <span className="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-ink/[0.04] dark:bg-fog/[0.06]">
            <PlatformMark platform={platform} size={24} />
          </span>
          <div className="min-w-0">
            <h1 className="text-[20px] font-bold leading-tight text-ink dark:text-fog">{title}</h1>
            <p className="mt-0.5 max-w-2xl text-[13px] leading-relaxed text-ink/45 dark:text-fog/45">
              {subtitle}
            </p>
          </div>
        </header>

        <ol className="mt-5 flex items-center gap-1.5 overflow-x-auto" aria-label="Onboarding steps">
          {steps.map((step, i) => {
            const done = i < current;
            const active = i === current;
            const clickable = done && Boolean(onStepClick);
            const inner = (
              <>
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                    done
                      ? "bg-emerald-600 text-white"
                      : active
                        ? "bg-deep-violet text-white"
                        : "bg-ink/[0.06] text-ink/40 dark:bg-fog/[0.08] dark:text-fog/40"
                  }`}
                >
                  {done ? (
                    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" className="h-3 w-3" aria-hidden>
                      <path d="M3.5 8.5l3 3 6-7" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : (
                    i + 1
                  )}
                </span>
                <span
                  className={`whitespace-nowrap text-[12px] font-semibold ${
                    active
                      ? "text-ink dark:text-fog"
                      : done
                        ? "text-ink/60 dark:text-fog/60"
                        : "text-ink/35 dark:text-fog/35"
                  }`}
                >
                  {step.label}
                </span>
              </>
            );
            return (
              <li key={step.key} className="flex items-center gap-1.5">
                {i > 0 && (
                  <span aria-hidden className="h-px w-4 shrink-0 bg-ink/10 dark:bg-fog/10" />
                )}
                {clickable ? (
                  <button
                    type="button"
                    onClick={() => onStepClick?.(i)}
                    className="flex items-center gap-1.5 rounded-lg px-1 py-1 outline-none transition hover:bg-ink/[0.03] focus-visible:ring-2 focus-visible:ring-deep-violet/40 dark:hover:bg-fog/[0.05]"
                  >
                    {inner}
                  </button>
                ) : (
                  <span
                    aria-current={active ? "step" : undefined}
                    className="flex items-center gap-1.5 px-1 py-1"
                  >
                    {inner}
                  </span>
                )}
              </li>
            );
          })}
        </ol>

        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
          <section className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink sm:p-5">
            {children}
          </section>
          {aside && <aside className="space-y-3">{aside}</aside>}
        </div>
      </div>
    </div>
  );
}

/** Small "why this matters" list used in the rail. */
export function BenefitList({
  title,
  items,
}: {
  title: string;
  items: { icon: string; label: string; body: string }[];
}) {
  return (
    <div className="rounded-xl border border-ink/[0.06] bg-white p-4 dark:border-fog/[0.06] dark:bg-ink">
      <p className="text-[11px] font-bold uppercase tracking-wide text-ink/40 dark:text-fog/40">
        {title}
      </p>
      <ul className="mt-2.5 space-y-3">
        {items.map((item) => (
          <li key={item.label} className="flex gap-2.5">
            <span aria-hidden className="text-[15px] leading-5">{item.icon}</span>
            <div className="min-w-0">
              <p className="text-[12.5px] font-semibold text-ink dark:text-fog">{item.label}</p>
              <p className="mt-0.5 text-[11.5px] leading-relaxed text-ink/45 dark:text-fog/45">
                {item.body}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "What you'll need" checklist rail (read-only). */
export function RequirementList({ items }: { items: string[] }) {
  return (
    <div className="rounded-xl border border-ink/[0.06] bg-ink/[0.02] p-4 dark:border-fog/[0.06] dark:bg-fog/[0.03]">
      <p className="text-[11px] font-bold uppercase tracking-wide text-ink/40 dark:text-fog/40">
        What you&rsquo;ll need
      </p>
      <ul className="mt-2 space-y-1.5">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-[11.5px] leading-relaxed text-ink/60 dark:text-fog/60">
            <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink/25 dark:bg-fog/25" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Checkbox row used by the pre-flight screens. */
export function CheckRow({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  children: ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-ink/[0.06] bg-white px-3 py-2.5 transition hover:border-deep-violet/25 dark:border-fog/[0.08] dark:bg-ink">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 accent-[#5b2d8e]"
      />
      <span className="text-[12.5px] leading-relaxed text-ink/75 dark:text-fog/75">{children}</span>
    </label>
  );
}

/** Highlighted callout used by the Wati-style "connect your number" screens. */
export function GuidelineNote({
  title,
  lines,
}: {
  title: string;
  lines: string[];
}) {
  return (
    <div className="rounded-xl border border-amber-300/60 bg-amber-50 p-3 dark:border-amber-500/25 dark:bg-amber-500/10">
      <p className="text-[11px] font-bold uppercase tracking-wide text-amber-800 dark:text-amber-300">
        {title}
      </p>
      <ul className="mt-1.5 space-y-1">
        {lines.map((line) => (
          <li key={line} className="text-[11.5px] leading-relaxed text-amber-800/85 dark:text-amber-300/85">
            · {line}
          </li>
        ))}
      </ul>
    </div>
  );
}
export function StepActions({
  children,
  hint,
}: {
  children: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="mt-5 flex flex-col gap-2 border-t border-ink/[0.05] pt-4 dark:border-fog/[0.06] sm:flex-row sm:items-center">
      {children}
      {hint && (
        <span className="text-[11px] leading-relaxed text-ink/40 dark:text-fog/40 sm:ml-auto sm:text-right">
          {hint}
        </span>
      )}
    </div>
  );
}

export function PrimaryButton({
  children,
  onClick,
  disabled,
  type = "button",
  href,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  type?: "button" | "submit";
  href?: string;
}) {
  const cls =
    "inline-flex min-h-10 items-center justify-center rounded-lg bg-deep-violet px-4 text-[13px] font-semibold text-white shadow-sm outline-none transition hover:bg-deep-violet/90 focus-visible:ring-2 focus-visible:ring-deep-violet/40 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50";
  if (href) {
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={cls}>
      {children}
    </button>
  );
}

export function SecondaryButton({
  children,
  onClick,
  disabled,
  href,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  href?: string;
}) {
  const cls =
    "inline-flex min-h-10 items-center justify-center rounded-lg border border-ink/10 bg-white px-4 text-[13px] font-semibold text-ink/70 outline-none transition hover:border-deep-violet/30 hover:text-deep-violet focus-visible:ring-2 focus-visible:ring-deep-violet/40 focus-visible:ring-offset-2 disabled:opacity-50 dark:border-fog/10 dark:bg-ink dark:text-fog/70";
  if (href) {
    return (
      <Link href={href} className={cls}>
        {children}
      </Link>
    );
  }
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={cls}>
      {children}
    </button>
  );
}

export function StepHeading({
  eyebrow,
  title,
  body,
}: {
  eyebrow?: string;
  title: string;
  body?: ReactNode;
}) {
  return (
    <div>
      {eyebrow && (
        <p className="text-[11px] font-bold uppercase tracking-wide text-deep-violet dark:text-violet-soft">
          {eyebrow}
        </p>
      )}
      <h2 className="mt-1 text-[16px] font-bold text-ink dark:text-fog">{title}</h2>
      {body && (
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink/50 dark:text-fog/50">{body}</p>
      )}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] leading-relaxed text-red-700 dark:border-red-500/25 dark:bg-red-500/10 dark:text-red-300"
    >
      {children}
    </p>
  );
}
