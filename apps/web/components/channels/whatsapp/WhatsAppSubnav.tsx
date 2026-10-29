"use client";

/* Section nav for the WhatsApp area: the hub plus the two surfaces that only
 * make sense there (Catalog, Templates). Keeping them under the WhatsApp
 * dashboard is deliberate — they are not product-wide pages. */

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/dashboard/channels/whatsapp", label: "Overview" },
  { href: "/dashboard/channels/whatsapp/catalog", label: "Catalog" },
  { href: "/dashboard/channels/whatsapp/templates", label: "Templates" },
];

export default function WhatsAppSubnav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="WhatsApp sections"
      className="mb-5 flex gap-1 overflow-x-auto border-b border-ink/[0.08] dark:border-fog/[0.1]"
    >
      {TABS.map((tab) => {
        const active =
          pathname === tab.href ||
          (tab.href !== "/dashboard/channels/whatsapp" &&
            pathname.startsWith(`${tab.href}/`));
        return (
          <Link
            key={tab.href}
            href={tab.href}
            aria-current={active ? "page" : undefined}
            className={`min-h-10 shrink-0 border-b-[3px] px-3 text-[12px] font-bold uppercase tracking-wide transition ${
              active
                ? "border-deep-violet text-deep-violet dark:border-fog dark:text-fog"
                : "border-transparent text-ink/45 hover:text-ink/75 dark:text-fog/45 dark:hover:text-fog/75"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
