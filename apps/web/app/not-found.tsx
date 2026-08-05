import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-ink/[0.06] text-ink/30 dark:bg-fog/[0.06] dark:text-fog/30">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="h-7 w-7">
          <circle cx="12" cy="12" r="10" />
          <path d="M16 16s-1.5-2-4-2-4 2-4 2" />
          <line x1="9" y1="9" x2="9.01" y2="9" />
          <line x1="15" y1="9" x2="15.01" y2="9" />
        </svg>
      </div>
      <div className="text-center">
        <h2 className="text-[16px] font-bold text-ink dark:text-fog">Page not found</h2>
        <p className="mt-1 text-[12px] text-ink/40 dark:text-fog/40">
          The page you are looking for does not exist.
        </p>
      </div>
      <Link
        href="/dashboard"
        className="rounded-lg bg-deep-violet px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-deep-violet/90"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}
