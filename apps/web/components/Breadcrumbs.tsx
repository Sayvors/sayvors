"use client";

import Link from "next/link";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export default function Breadcrumbs({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav className="flex items-center gap-1.5 text-[12px]">
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={i} className="flex items-center gap-1.5">
            {i > 0 && (
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" className="h-3 w-3 text-ink/20 dark:text-fog/20">
                <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
            {isLast || !item.href ? (
              <span className="font-medium text-ink/70 dark:text-fog/70">{item.label}</span>
            ) : (
              <Link href={item.href} className="text-ink/40 transition hover:text-ink/60 dark:text-fog/40 dark:hover:text-fog/60">
                {item.label}
              </Link>
            )}
          </span>
        );
      })}
    </nav>
  );
}
